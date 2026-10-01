from __future__ import annotations

import contextlib
import contextvars
import logging
import threading
from typing import TYPE_CHECKING, Any, cast

import bson
import pymongo
from bson.errors import BSONError
from pymongo.errors import OperationFailure, PyMongoError

from client_query_cache._core.barrier import (
    BarrierOutcome,
    BarrierProgress,
    barrier_error_for_driver_failure,
    barrier_error_for_startup_failure,
    raise_for_outcome,
    remaining_seconds,
    target_start_time,
)
from client_query_cache._core.errors import (
    BarrierClosedError,
    BarrierTimeoutError,
    StreamLifecycleError,
    StreamStartupError,
)
from client_query_cache._core.stream_events import (
    build_change_stream_pipeline,
    is_unresumable_change_stream_error,
    route_change_event,
)
from client_query_cache._core.stream_health import RetryBackoff, StreamHealth
from client_query_cache._core.stream_options import DEFAULT_MAX_AWAIT_TIME_MS

if TYPE_CHECKING:
    from collections.abc import Mapping

    from bson import Timestamp
    from pymongo import MongoClient
    from pymongo.synchronous.change_stream import DatabaseChangeStream
    from pymongo.synchronous.database import Database

    from client_query_cache._core.manager import CacheCore

MINIMUM_SERVER_VERSION = (8, 0)

logger = logging.getLogger(__name__)


class _ThreadWaiter:
    __slots__ = ("event", "outcome", "target")

    def __init__(self, target: str) -> None:
        self.target = target
        self.outcome: BarrierOutcome | None = None
        self.event = threading.Event()

    def resolve(self, outcome: BarrierOutcome) -> None:
        self.outcome = outcome
        self.event.set()


class DatabaseStreamSupervisor:
    __slots__ = (
        "_backoff",
        "_cache",
        "_continuity_lost",
        "_database",
        "_health",
        "_health_lock",
        "_lifecycle_lock",
        "_max_await_time_ms",
        "_progress",
        "_progress_lock",
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
        max_await_time_ms: int = DEFAULT_MAX_AWAIT_TIME_MS,
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
        self._continuity_lost = False
        self._progress = BarrierProgress()
        self._progress_lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._cache.set_database_available(self._database.name, available=False)

    @property
    def healthy(self) -> bool:
        with self._health_lock:
            return self._health is StreamHealth.HEALTHY

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
            if self._stop_event.is_set():
                assert self._stream is not None
                with contextlib.suppress(PyMongoError):
                    self._stream.close()
                self._set_health(StreamHealth.CLOSED)
                message = "stop() was called while start() was still connecting"
                raise StreamLifecycleError(message)
            self._set_health(StreamHealth.HEALTHY)
            self._thread = threading.Thread(
                target=self._run,
                name=f"client-query-cache-stream-{self._database.name}",
                daemon=True,
                context=contextvars.Context(),
            )
            self._thread.start()

    def stop(self) -> None:
        with self._lifecycle_lock:
            self._stop_event.set()
            self._set_health(StreamHealth.CLOSED)
            with self._progress_lock:
                self._progress.close()
            stream = self._stream
            if stream is not None:
                try:
                    stream.close()
                except PyMongoError:
                    logger.warning(
                        "change stream close failed during shutdown",
                        extra={"database": self._database.name},
                        exc_info=True,
                    )
            thread = self._thread
        if thread is not None:
            thread.join()
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
            with contextlib.suppress(PyMongoError):
                previous_stream.close()
        if self._stop_event.is_set():
            with contextlib.suppress(PyMongoError):
                self._stream.close()

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
                event = self._stream.try_next()
            except PyMongoError:
                self._handle_stream_failure()
                continue
            token = cast("Mapping[str, Any]", self._stream.resume_token)
            if event is None:
                if not self._stream.alive:
                    self._handle_stream_failure()
                    continue
                self._publish_progress(token)
                continue
            must_reopen = route_change_event(self._cache, self._database.name, event)
            self._record_logical_event_bytes(event)
            self._publish_progress(token)
            if must_reopen:
                self._reopen_after_invalidate()

    def _publish_progress(self, token: Mapping[str, Any]) -> None:
        self._resume_token = token
        with self._progress_lock:
            if self._continuity_lost:
                self._continuity_lost = False
                self._progress.restart(token["_data"])
            else:
                self._progress.advance(token["_data"])

    def wait_for_boundary(self, operation_time: Timestamp, deadline: float) -> None:
        waiter = _ThreadWaiter(self._acquire_target(operation_time, deadline))
        with self._progress_lock:
            outcome = self._progress.register(waiter)
        if outcome is None:
            try:
                waiter.event.wait(remaining_seconds(deadline))
            finally:
                with self._progress_lock:
                    self._progress.discard(waiter)
            outcome = waiter.outcome
            if outcome is None:
                raise BarrierTimeoutError("the barrier deadline expired")
        raise_for_outcome(outcome)

    def _acquire_target(self, operation_time: Timestamp, deadline: float) -> str:
        try:
            with pymongo.timeout(remaining_seconds(deadline)):
                stream = self._database.watch(
                    start_at_operation_time=target_start_time(operation_time),
                    batch_size=0,
                )
                token = cast("Mapping[str, Any]", stream.resume_token)
                with contextlib.suppress(PyMongoError):
                    stream.close()
        except PyMongoError as exc:
            raise barrier_error_for_driver_failure(exc) from exc
        return cast("str", token["_data"])

    def _record_logical_event_bytes(self, event: Mapping[str, Any]) -> None:
        try:
            encoded_length = len(
                bson.encode(dict(event), codec_options=self._database.codec_options)
            )
        except BSONError, TypeError, ValueError:
            return
        self._cache.record_logical_event_bytes(self._database.name, encoded_length)

    def _handle_stream_failure(self) -> None:
        if self._stop_event.is_set():
            return
        self._set_health(StreamHealth.RECONNECTING)
        if self._resume_token is None:
            self._lose_continuity()
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
                    self._lose_continuity()
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

    def _lose_continuity(self) -> None:
        self._clear_namespaces_for_database()
        self._resume_token = None
        with self._progress_lock:
            self._continuity_lost = True
            self._progress.lose_continuity()

    def _clear_namespaces_for_database(self) -> None:
        for namespace in self._cache.namespaces_for_database(self._database.name):
            self._cache.clear_namespace(namespace)
        self._cache.reset_stream_cost_statistics(self._database.name)


class ChangeStreamCoordinator:
    __slots__ = (
        "_cache",
        "_client",
        "_closed",
        "_lock",
        "_max_await_time_ms",
        "_supervisors",
    )

    def __init__(
        self,
        client: MongoClient[Any],
        cache: CacheCore,
        *,
        max_await_time_ms: int = DEFAULT_MAX_AWAIT_TIME_MS,
    ) -> None:
        self._client = client
        self._max_await_time_ms = max_await_time_ms
        self._cache = cache
        self._supervisors: dict[str, DatabaseStreamSupervisor] = {}
        self._closed = False
        self._lock = threading.Lock()

    def activate_database(self, name: str) -> DatabaseStreamSupervisor | None:
        with self._lock:
            if self._closed:
                raise StreamLifecycleError("coordinator is closed")
            try:
                return self._supervisors[name]
            except KeyError:
                pass
            try:
                return self._start_supervisor(name)
            except StreamStartupError:
                return None

    def activate_database_until(
        self, name: str, deadline: float
    ) -> DatabaseStreamSupervisor:
        if not self._lock.acquire(timeout=remaining_seconds(deadline)):
            raise BarrierTimeoutError("the barrier deadline expired during activation")
        try:
            if self._closed:
                raise BarrierClosedError("the manager was closed")
            try:
                return self._supervisors[name]
            except KeyError:
                pass
            try:
                with pymongo.timeout(remaining_seconds(deadline)):
                    return self._start_supervisor(name)
            except StreamStartupError as exc:
                raise barrier_error_for_startup_failure(exc) from exc
        finally:
            self._lock.release()

    def _start_supervisor(self, name: str) -> DatabaseStreamSupervisor:
        supervisor = DatabaseStreamSupervisor(
            self._client[name],
            self._cache,
            max_await_time_ms=self._max_await_time_ms,
        )
        try:
            supervisor.start()
        except StreamStartupError:
            logger.warning(
                "change stream startup failed for database %r; reads for "
                "this database will bypass the cache",
                name,
                exc_info=True,
            )
            raise
        self._supervisors[name] = supervisor
        return supervisor

    def close(self) -> None:
        with self._lock:
            self._closed = True
            supervisors = list(self._supervisors.values())
            self._supervisors.clear()
        for supervisor in supervisors:
            supervisor.stop()
