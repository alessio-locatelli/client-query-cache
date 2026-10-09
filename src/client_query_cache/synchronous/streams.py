from __future__ import annotations

import logging
import threading
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

    from pymongo import MongoClient
    from pymongo.synchronous.change_stream import DatabaseChangeStream
    from pymongo.synchronous.database import Database

    from client_query_cache._core.manager import CacheCore

MINIMUM_SERVER_VERSION = (8, 0)

logger = logging.getLogger(__name__)


class DatabaseStreamSupervisor:
    __slots__ = (
        "_backoff",
        "_cache",
        "_database",
        "_health",
        "_health_lock",
        "_lifecycle_lock",
        "_max_await_time_ms",
        "_resume_token",
        "_stop_event",
        "_stream",
        "_thread",
    )

    def __init__(
        self,
        database: Database[Any],
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
        self._health_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._stream: DatabaseChangeStream[Any] | None = None
        self._resume_token: Mapping[str, Any] | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cache.set_database_available(self._database.name, available=False)

    @property
    def healthy(self) -> bool:
        with self._health_lock:
            return self._health is StreamHealth.HEALTHY

    def health_status(self) -> StreamHealthStatus:
        with self._health_lock:
            return public_stream_health(self._health)

    def start(self) -> None:
        with self._lifecycle_lock:
            if self._health is not StreamHealth.STARTING:
                message = "start() may only be called once per supervisor instance"
                raise StreamLifecycleError(message)
            self._set_health(StreamHealth.CONNECTING)
        self._clear_namespaces_for_database()
        try:
            self._ensure_server_supports_expanded_events()
            self._open_stream(resume_token=None, use_start_after=False)
        except StreamStartupError:
            self._set_health(StreamHealth.CLOSED)
            raise
        except PyMongoError as exc:
            self._set_health(StreamHealth.CLOSED)
            message = (
                f"failed to open change stream for database {self._database.name!r}"
            )
            raise StreamStartupError(message) from exc
        with self._lifecycle_lock:
            stopped = self._stop_event.is_set()
            if not stopped:
                self._set_health(StreamHealth.HEALTHY)
                self._thread = threading.Thread(
                    target=self._run,
                    name=f"client-query-cache-stream-{self._database.name}",
                    daemon=True,
                )
                self._thread.start()
        if stopped:
            self.stop()
            message = "stop() was called while start() was still connecting"
            raise StreamLifecycleError(message)

    def request_stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_event.set()
            self._set_health(StreamHealth.CLOSED)

    def stop(self) -> None:
        self.request_stop()
        with self._lifecycle_lock:
            stream = self._stream
            thread = self._thread
        if stream is not None:
            try:
                stream.close()
            except PyMongoError:
                logger.warning(
                    "change stream close failed during shutdown",
                    extra={"database": self._database.name},
                    exc_info=True,
                )
        if thread is not None:
            thread.join()
        with self._lifecycle_lock:
            if self._stream is stream:
                self._stream = None
            self._set_health(StreamHealth.CLOSED)

    def _ensure_server_supports_expanded_events(self) -> None:
        server_info = self._database.client.server_info()
        version = tuple(server_info["versionArray"][:2])
        if version < MINIMUM_SERVER_VERSION:
            message = (
                f"MongoDB server version {server_info['version']} is not supported; "
                "client_query_cache requires MongoDB 8.0 or newer"
            )
            raise StreamStartupError(message)

    def _open_stream(
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
        self._stream = self._database.watch(build_change_stream_pipeline(), **kwargs)
        if previous_stream is not None:
            try:
                previous_stream.close()
            except PyMongoError:
                pass

        if self._stop_event.is_set():
            try:
                self._stream.close()
            except PyMongoError:
                pass
            self._stream = None

    def _set_health(self, health: StreamHealth) -> None:
        with self._lifecycle_lock:
            if self._stop_event.is_set() and health is StreamHealth.HEALTHY:
                health = StreamHealth.CLOSED
            with self._health_lock:
                self._cache.set_database_available(
                    self._database.name, available=health is StreamHealth.HEALTHY
                )
                self._health = health

    def _run(self) -> None:
        while not self._stop_event.is_set():
            assert self._stream is not None
            self._cache.record_stream_poll(self._database.name)
            try:
                event = self._stream.next()
            except StopIteration:
                self._handle_stream_failure()
                continue
            except PyMongoError:
                self._handle_stream_failure()
                continue
            self._resume_token = self._stream.resume_token
            must_reopen = route_change_event(self._cache, self._database.name, event)
            self._record_logical_event_bytes(event)
            if must_reopen:
                self._reopen_after_invalidate()

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

    def _handle_stream_failure(self) -> None:
        if self._stop_event.is_set():
            return
        self._set_health(StreamHealth.RECONNECTING)
        if self._resume_token is None:
            self._clear_namespaces_for_database()
        self._reopen_with_backoff(use_start_after=False)

    def _reopen_after_invalidate(self) -> None:
        self._set_health(StreamHealth.RECONNECTING)
        self._reopen_with_backoff(use_start_after=True)

    def _reopen_with_backoff(self, *, use_start_after: bool) -> None:
        while not self._stop_event.is_set():
            try:
                self._open_stream(
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
                if self._stop_event.wait(delay):
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
        "_shutdown_complete",
        "_supervisors",
    )

    def __init__(
        self,
        client: MongoClient[Any],
        cache: CacheCore,
        *,
        max_await_time_ms: MaxAwaitTimeMs = DEFAULT_MAX_AWAIT_TIME_MS,
    ) -> None:
        self._client = client
        self._max_await_time_ms = max_await_time_ms
        self._cache = cache
        self._activations: dict[
            str, StreamActivation[DatabaseStreamSupervisor, threading.Event]
        ] = {}
        self._supervisors: dict[str, DatabaseStreamSupervisor] = {}
        self._closed = False
        self._health_registry = StreamHealthRegistry()
        self._lock = threading.Lock()
        self._shutdown_complete = threading.Event()

    def activate_database(self, name: str) -> DatabaseStreamSupervisor | None:
        with self._lock:
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
                activation = StreamActivation(supervisor, threading.Event())
                self._activations[name] = activation
            else:
                activation.supervisor = supervisor
                activation.pending = True
                activation.completion.clear()
            self._health_registry.record_connecting(name)
        published = False
        try:
            try:
                supervisor.start()
            except StreamStartupError:
                with self._lock:
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
            with self._lock:
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
                    supervisor.stop()
                finally:
                    with self._lock:
                        if not self._closed:
                            self._health_registry.record_startup_failure(name)
                        activation.pending = False
                        activation.completion.set()
            else:
                activation.completion.set()

    def stream_health_snapshot(self, database_name: str) -> StreamHealthSnapshot:
        return self._health_registry.snapshot(database_name)

    def close(self) -> None:
        with self._lock:
            owns_cleanup = not self._closed
            if owns_cleanup:
                self._closed = True
                self._health_registry.close()
                supervisors = tuple(self._supervisors.values())
                activations = tuple(self._activations.values())
                for supervisor in supervisors:
                    supervisor.request_stop()
                for activation in activations:
                    activation.supervisor.request_stop()
                self._supervisors.clear()
                self._activations.clear()
        if not owns_cleanup:
            self._shutdown_complete.wait()
            return
        try:
            for activation in activations:
                activation.completion.wait()
            for supervisor in supervisors:
                supervisor.stop()
        finally:
            self._shutdown_complete.set()
