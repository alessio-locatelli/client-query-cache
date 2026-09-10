from __future__ import annotations

import logging
import threading
from typing import TYPE_CHECKING, Any

from pymongo.errors import OperationFailure, PyMongoError

from mongo_client_cache._core.errors import StreamStartupError
from mongo_client_cache._core.stream_events import (
    build_change_stream_pipeline,
    is_unresumable_change_stream_error,
    route_change_event,
)
from mongo_client_cache._core.stream_health import RetryBackoff, StreamHealth

if TYPE_CHECKING:
    from collections.abc import Mapping

    from pymongo import MongoClient
    from pymongo.synchronous.change_stream import DatabaseChangeStream
    from pymongo.synchronous.database import Database

    from mongo_client_cache._core.keys import NamespaceId
    from mongo_client_cache._core.manager import CacheCore

MINIMUM_SERVER_VERSION = (6, 0)
DEFAULT_MAX_AWAIT_TIME_MS = 1_000

logger = logging.getLogger(__name__)


class DatabaseStreamSupervisor:
    __slots__ = (
        "_backoff",
        "_cache",
        "_database",
        "_health",
        "_health_lock",
        "_max_await_time_ms",
        "_namespaces",
        "_namespaces_lock",
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
        self._namespaces: set[NamespaceId] = set()
        self._namespaces_lock = threading.Lock()
        self._health = StreamHealth.STARTING
        self._health_lock = threading.Lock()
        self._stream: DatabaseChangeStream[Any] | None = None
        self._resume_token: Mapping[str, Any] | None = None
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None

    @property
    def healthy(self) -> bool:
        with self._health_lock:
            return self._health is StreamHealth.HEALTHY

    def start(self) -> None:
        self._ensure_server_supports_expanded_events()
        try:
            self._open_stream(resume_token=None, use_start_after=False)
        except PyMongoError as exc:
            message = (
                f"failed to open change stream for database {self._database.name!r}"
            )
            raise StreamStartupError(message) from exc
        self._set_health(StreamHealth.HEALTHY)
        self._thread = threading.Thread(
            target=self._run,
            name=f"mongo-client-cache-stream-{self._database.name}",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        stream = self._stream
        if stream is not None:
            stream.close()
        thread = self._thread
        if thread is not None:
            thread.join()
        self._set_health(StreamHealth.CLOSED)

    def _ensure_server_supports_expanded_events(self) -> None:
        server_info = self._database.client.server_info()
        version = tuple(server_info["versionArray"][:2])
        if version < MINIMUM_SERVER_VERSION:
            message = (
                f"MongoDB server version {server_info['version']} does not support "
                "change-stream expanded events; version 6.0 or newer is required"
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
        self._stream = self._database.watch(build_change_stream_pipeline(), **kwargs)

    def _set_health(self, health: StreamHealth) -> None:
        with self._health_lock:
            self._health = health

    def _run(self) -> None:
        while not self._stop_event.is_set():
            assert self._stream is not None
            try:
                event = self._stream.next()
            except StopIteration:
                return
            except PyMongoError:
                self._handle_stream_failure()
                continue
            self._resume_token = self._stream.resume_token
            with self._namespaces_lock:
                must_reopen = route_change_event(self._cache, event, self._namespaces)
            if must_reopen:
                self._reopen_after_invalidate()

    def _handle_stream_failure(self) -> None:
        if self._stop_event.is_set():
            return
        self._set_health(StreamHealth.RECONNECTING)
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
                    self._clear_known_namespaces()
                    self._resume_token = None
                    use_start_after = False
                    continue
                delay = self._backoff.next_delay()
                if self._stop_event.wait(delay):
                    return
                continue
            else:
                self._backoff.reset()
                self._set_health(StreamHealth.HEALTHY)
                return

    def _clear_known_namespaces(self) -> None:
        with self._namespaces_lock:
            for namespace in list(self._namespaces):
                self._cache.clear_namespace(namespace)
            self._namespaces.clear()


class ChangeStreamCoordinator:
    __slots__ = ("_cache", "_client", "_lock", "_supervisors")

    def __init__(self, client: MongoClient[Any], cache: CacheCore) -> None:
        self._client = client
        self._cache = cache
        self._supervisors: dict[str, DatabaseStreamSupervisor] = {}
        self._lock = threading.Lock()

    def activate_database(self, name: str) -> DatabaseStreamSupervisor:
        with self._lock:
            supervisor = self._supervisors.get(name)
            if supervisor is None:
                supervisor = DatabaseStreamSupervisor(self._client[name], self._cache)
                supervisor.start()
                self._supervisors[name] = supervisor
            return supervisor

    def close(self) -> None:
        with self._lock:
            supervisors = list(self._supervisors.values())
            self._supervisors.clear()
        for supervisor in supervisors:
            supervisor.stop()
