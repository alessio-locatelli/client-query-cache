# Research prototype: the owner reuses private supervisor seams for fault injection.
# ruff: noqa: SLF001
from __future__ import annotations

import fcntl
import hmac
import pathlib
import secrets
import selectors
import socket
import threading
import time
from collections import deque
from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Final, Literal, TextIO

from bson.int64 import Int64
from pymongo import MongoClient
from pymongo.errors import OperationFailure
from pymongo.monitoring import CommandListener

from benchmarks.stream_cost.shared_cache.wire import (
    LENGTH_BYTES,
    PROTOCOL_VERSION,
    KeyCache,
    ProtocolError,
    decode_frame,
    decode_key,
    encode_frame,
    frame_length,
)
from client_query_cache._core.entries import AdmissionOutcome
from client_query_cache._core.errors import StreamLifecycleError
from client_query_cache._core.find_reads import FindReadShape
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.manager import (
    CacheCore,
    CacheCoreConfig,
    IdentityCapture,
    NamespaceCapture,
)
from client_query_cache._core.stream_cost import LagCaptureWindowConfig
from client_query_cache._types import (
    MaxAwaitTimeMs,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from client_query_cache.synchronous.streams import ChangeStreamCoordinator

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from multiprocessing.connection import Connection

    from pymongo.monitoring import (
        CommandFailedEvent,
        CommandStartedEvent,
        CommandSucceededEvent,
    )

    from client_query_cache._core.find_reads import FindSource
    from client_query_cache.synchronous.streams import DatabaseStreamSupervisor

type Message = dict[str, object]
type ActivationState = Literal["pending", "active", "failed"]

_RECEIVE_BYTES: Final = 262_144
_SWEEP_SECONDS: Final = 0.05
_ACTIVATION_RETRY_SECONDS: Final = 1.0
_HISTORY_LOST: Final = 286
_KEY_CACHE_ENTRIES: Final = 1024


@dataclass(frozen=True, slots=True)
class TransportLimits:
    rpc_deadline_seconds: PositiveFloat
    progress_expiry_seconds: PositiveFloat
    queued_bytes_per_connection: PositiveInt
    requests_per_connection: PositiveInt
    connections: PositiveInt
    captures: PositiveInt
    capture_seconds: PositiveFloat
    frame_overhead_bytes: PositiveInt


@dataclass(frozen=True, slots=True)
class OwnerConfig:
    socket_path: str
    capability: bytes
    mongodb_uri: str
    client_options: Mapping[str, object]
    databases: tuple[str, ...]
    budget_bytes: PositiveInt
    max_entry_bytes: PositiveInt
    max_await_time_ms: MaxAwaitTimeMs
    limits: TransportLimits
    lag_capture: tuple[PositiveInt, PositiveInt, NonNegativeInt]

    @property
    def frame_limit(self) -> PositiveInt:
        return self.max_entry_bytes + self.limits.frame_overhead_bytes


class UpstreamProgress(CommandListener):
    def __init__(self) -> None:
        self.observed: dict[str, NonNegativeFloat] = {}
        self.counts: dict[str, NonNegativeInt] = {}
        self._lock = threading.Lock()

    def _count(self, key: str) -> None:
        with self._lock:
            try:
                self.counts[key] += 1
            except KeyError:
                self.counts[key] = 1

    def started(self, event: CommandStartedEvent) -> None:
        self._count(f"{event.command_name}:requested")
        if event.command_name == "aggregate" and any(
            "$changeStream" in stage for stage in event.command["pipeline"]
        ):
            self._count("stream:opened")

    def succeeded(self, event: CommandSucceededEvent) -> None:
        self._count(f"{event.command_name}:completed")
        if event.command_name in {"getMore", "aggregate"}:
            self.observed[event.database_name] = time.monotonic()

    def failed(self, event: CommandFailedEvent) -> None:
        self._count(f"{event.command_name}:failed")

    def snapshot(self) -> dict[str, NonNegativeInt]:
        with self._lock:
            return dict(self.counts)


@dataclass(slots=True)
class _Handle:
    session: NonNegativeInt
    capture: IdentityCapture | NamespaceCapture
    database: str
    lease: NonNegativeInt
    expires: NonNegativeFloat
    shape: object = None
    find_source: FindSource | None = None


@dataclass(slots=True)
class _Connection:
    sock: socket.socket
    inbox: bytearray = field(default_factory=bytearray)
    outbox: deque[memoryview] = field(default_factory=deque)
    queued: NonNegativeInt = 0
    replies: NonNegativeInt = 0
    session: NonNegativeInt | None = None
    handles: set[NonNegativeInt] = field(default_factory=set)
    writable: bool = False
    closed: bool = False


@dataclass(slots=True)
class OwnerCounters:
    connections_accepted: NonNegativeInt = 0
    connections_rejected: NonNegativeInt = 0
    detached: NonNegativeInt = 0
    protocol_errors: NonNegativeInt = 0
    unauthorized: NonNegativeInt = 0
    configuration_mismatches: NonNegativeInt = 0
    requests: NonNegativeInt = 0
    hits: NonNegativeInt = 0
    misses: NonNegativeInt = 0
    bypasses: NonNegativeInt = 0
    refreshes: NonNegativeInt = 0
    admissions: NonNegativeInt = 0
    admitted: NonNegativeInt = 0
    rejected_admissions: NonNegativeInt = 0
    expired_captures: NonNegativeInt = 0
    capture_limit_misses: NonNegativeInt = 0
    lease_expiries: NonNegativeInt = 0
    ipc_bytes_received: NonNegativeInt = 0
    ipc_bytes_sent: NonNegativeInt = 0
    busy_seconds: NonNegativeFloat = 0.0
    peak_queued_bytes: NonNegativeInt = 0
    peak_captures: NonNegativeInt = 0


class SharedCacheOwner:
    __slots__ = (
        "_activation",
        "_activation_lock",
        "_connections",
        "_handles",
        "_keys",
        "_lease_epoch",
        "_lease_live",
        "_listener",
        "_lock_file",
        "_next_handle",
        "_next_session",
        "_paused_until",
        "_selector",
        "client",
        "config",
        "core",
        "counters",
        "incarnation",
        "progress",
        "streams",
    )

    def __init__(self, config: OwnerConfig) -> None:
        self.config = config
        self.incarnation = Int64(secrets.randbits(63))
        self.progress = UpstreamProgress()
        self.client: MongoClient[dict[str, object]] = MongoClient(
            config.mongodb_uri,
            event_listeners=[self.progress],
            **config.client_options,  # type: ignore[arg-type]
        )
        self.core = CacheCore(
            CacheCoreConfig(
                shared_budget_bytes=config.budget_bytes,
                max_entry_bytes=config.max_entry_bytes,
                lag_capture_window_config=LagCaptureWindowConfig(*config.lag_capture),
            )
        )
        self.streams = ChangeStreamCoordinator(
            self.client, self.core, max_await_time_ms=config.max_await_time_ms
        )
        self.counters = OwnerCounters()
        self._activation: dict[str, tuple[ActivationState, NonNegativeFloat]] = {}
        self._activation_lock = threading.Lock()
        self._lease_live: dict[str, bool] = {}
        self._lease_epoch: dict[str, NonNegativeInt] = {}
        self._handles: dict[NonNegativeInt, _Handle] = {}
        self._keys = KeyCache(_KEY_CACHE_ENTRIES)
        self._next_handle = 1
        self._next_session = 1
        self._connections: dict[int, _Connection] = {}
        self._selector = selectors.DefaultSelector()
        self._listener: socket.socket | None = None
        self._lock_file: TextIO | None = None
        self._paused_until = 0.0

    def bind(self) -> None:
        path = pathlib.Path(self.config.socket_path)
        lock = path.with_suffix(".lock").open("a", encoding="utf-8")
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as error:
            lock.close()
            message = "another owner already holds this endpoint"
            raise RuntimeError(message) from error
        self._lock_file = lock
        path.unlink(missing_ok=True)
        listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        listener.bind(str(path))
        path.chmod(0o600)
        listener.listen(self.config.limits.connections)
        listener.settimeout(0.0)
        self._listener = listener
        self._selector.register(listener, selectors.EVENT_READ, None)

    def lease_fresh(self, database: str, now: NonNegativeFloat) -> bool:
        try:
            observed = self.progress.observed[database]
        except KeyError:
            return False
        fresh = now - observed <= self.config.limits.progress_expiry_seconds
        try:
            live = self._lease_live[database]
        except KeyError:
            live = False
        if live and not fresh:
            self._lease_live[database] = False
            self._lease_epoch[database] = self._lease(database) + 1
            self.counters.lease_expiries += 1
        elif fresh and not live:
            self._lease_live[database] = True
        return fresh

    def _lease(self, database: str) -> NonNegativeInt:
        try:
            return self._lease_epoch[database]
        except KeyError:
            return 0

    def _activate(self, database: str, now: NonNegativeFloat) -> ActivationState:
        with self._activation_lock:
            try:
                state, since = self._activation[database]
            except KeyError:
                state, since = "failed", -_ACTIVATION_RETRY_SECONDS
            if state != "failed" or now - since < _ACTIVATION_RETRY_SECONDS:
                return state
            self._activation[database] = ("pending", now)
        threading.Thread(
            target=self._run_activation, args=(database,), daemon=True
        ).start()
        return "pending"

    def _run_activation(self, database: str) -> None:
        try:
            supervisor = self.streams.activate_database(database)
        except StreamLifecycleError:
            supervisor = None
        with self._activation_lock:
            self._activation[database] = (
                ("active", time.monotonic())
                if supervisor is not None
                else ("failed", time.monotonic())
            )

    def _gate(self, database: str, now: NonNegativeFloat) -> str | None:
        if database not in self.config.databases:
            return "database-not-authorized"
        if self._activate(database, now) != "active":
            return "stream-starting"
        if not self.core.is_database_available(database):
            return "stream-unavailable"
        if not self.lease_fresh(database, now):
            return "progress-expired"
        return None

    def _new_handle(
        self,
        connection: _Connection,
        capture: IdentityCapture | NamespaceCapture,
        now: NonNegativeFloat,
        *,
        shape: object = None,
        find_source: FindSource | None = None,
    ) -> NonNegativeInt | None:
        assert connection.session is not None
        if len(self._handles) >= self.config.limits.captures:
            self.counters.capture_limit_misses += 1
            self._drop_capture(capture)
            return None
        handle = self._next_handle
        self._next_handle += 1
        self._handles[handle] = _Handle(
            connection.session,
            capture,
            capture.namespace.database,
            self._lease(capture.namespace.database),
            now + self.config.limits.capture_seconds,
            shape,
            find_source,
        )
        connection.handles.add(handle)
        self.counters.peak_captures = max(
            self.counters.peak_captures, len(self._handles)
        )
        return handle

    def _drop_capture(self, capture: IdentityCapture | NamespaceCapture) -> None:
        if isinstance(capture, IdentityCapture):
            self.core.discard_identity_admission(capture)

    def _release(self, handle_id: NonNegativeInt) -> _Handle:
        handle = self._handles.pop(handle_id)
        self._drop_capture(handle.capture)
        return handle

    def _sweep(self, now: NonNegativeFloat) -> None:
        expired = tuple(
            handle_id
            for handle_id, handle in self._handles.items()
            if handle.expires <= now
        )
        for handle_id in expired:
            handle = self._release(handle_id)
            self.counters.expired_captures += 1
            for connection in self._connections.values():
                if connection.session == handle.session:
                    connection.handles.discard(handle_id)

    def _epoch_reply(self, namespace: NamespaceId, epoch: object) -> Message | None:
        current = self.core.current_epoch(namespace)
        if epoch != current:
            self.counters.refreshes += 1
            return {
                "r": "refresh",
                "epoch": current,
                "index_generation": self.core.current_index_generation(namespace),
            }
        return None

    def _handle_request(
        self, connection: _Connection, message: Message, now: NonNegativeFloat
    ) -> Message | None:
        operation = message["op"]
        if connection.session is None:
            if operation != "hello":
                self.counters.unauthorized += 1
                raise ProtocolError("attachment must authenticate first")
            return self._hello(connection, message)
        self.counters.requests += 1
        match operation:
            case "admit":
                self._admit(connection, message, now)
                return None
            case "discard":
                handle_id = message["handle"]
                if isinstance(handle_id, int) and handle_id in connection.handles:
                    connection.handles.discard(handle_id)
                    self._release(handle_id)
                return None
            case "observe":
                return {"r": "ok", **self.observation(now)}
        namespace = _namespace(message["ns"])
        reason = self._gate(namespace.database, now)
        if reason is not None:
            self.counters.bypasses += 1
            return {"r": "bypass", "reason": reason}
        match operation:
            case "metadata":
                return {
                    "r": "ok",
                    "epoch": self.core.current_epoch(namespace),
                    "index_generation": self.core.current_index_generation(namespace),
                }
            case "select-identity":
                refresh = self._epoch_reply(namespace, message["epoch"])
                if refresh is not None:
                    return refresh
                identity = decode_key(message["identity"])
                shape = self._keys.decode(message["shape"])
                value = self.core.lookup_identity_encoded(namespace, identity, shape)
                if value is not None:
                    self.counters.hits += 1
                    return {"r": "hit", "value": value}
                self.counters.misses += 1
                identity_capture = self.core.begin_identity_admission(
                    namespace, identity
                )
                return {
                    "r": "miss",
                    "handle": self._new_handle(
                        connection, identity_capture, now, shape=shape
                    ),
                }
            case "select-find":
                refresh = self._epoch_reply(namespace, message["epoch"])
                if refresh is not None:
                    return refresh
                limit = message["limit"]
                if not isinstance(limit, int) or isinstance(limit, bool):
                    raise ProtocolError("find limit must be an integer")
                shape = FindReadShape(self._keys.decode(message["family"]), limit)
                value = self.core.lookup_find_encoded(namespace, shape)
                if value is not None:
                    self.counters.hits += 1
                    return {"r": "hit", "value": value}
                self.counters.misses += 1
                namespace_capture = self.core.capture_namespace_generation(namespace)
                return {
                    "r": "miss",
                    "handle": self._new_handle(
                        connection,
                        namespace_capture,
                        now,
                        shape=shape.discriminator,
                        find_source=shape.source,
                    ),
                }
        raise ProtocolError("unknown operation")

    def _hello(self, connection: _Connection, message: Message) -> Message:
        capability = message["capability"]
        if not isinstance(capability, bytes) or not hmac.compare_digest(
            capability, self.config.capability
        ):
            self.counters.unauthorized += 1
            raise ProtocolError("attachment is not authorized")
        if (
            message["budget_bytes"] != self.config.budget_bytes
            or message["max_entry_bytes"] != self.config.max_entry_bytes
            or message["max_await_time_ms"] != self.config.max_await_time_ms
        ):
            self.counters.configuration_mismatches += 1
            return {"r": "error", "reason": "configuration-mismatch"}
        connection.session = self._next_session
        self._next_session += 1
        return {
            "r": "ok",
            "incarnation": self.incarnation,
            "session": connection.session,
            "databases": list(self.config.databases),
        }

    def _admit(
        self, connection: _Connection, message: Message, now: NonNegativeFloat
    ) -> None:
        self.counters.admissions += 1
        value = message["value"]
        if not isinstance(value, bytes):
            raise ProtocolError("admission value must be encoded bytes")
        handle_id = message["handle"]
        if not isinstance(handle_id, int) or handle_id not in connection.handles:
            self.counters.rejected_admissions += 1
            return
        connection.handles.discard(handle_id)
        handle = self._handles.pop(handle_id)
        if (
            handle.expires <= now
            or self._gate(handle.database, now) is not None
            or handle.lease != self._lease(handle.database)
        ):
            self.counters.rejected_admissions += 1
            self._drop_capture(handle.capture)
            return
        if isinstance(handle.capture, IdentityCapture):
            outcome = self.core.admit_identity_encoded(
                handle.capture, handle.shape, value
            )
        else:
            outcome = self.core.admit_namespace_encoded(
                handle.capture, handle.shape, value, find_source=handle.find_source
            )
        if outcome is AdmissionOutcome.ADMITTED:
            self.counters.admitted += 1
        else:
            self.counters.rejected_admissions += 1

    def observation(self, now: NonNegativeFloat) -> Message:
        snapshot = self.core.snapshot()
        return {
            "scope": "group",
            "incarnation": self.incarnation,
            "observed_monotonic": now,
            "cache": {
                "used_bytes": snapshot.used_bytes,
                "entry_count": snapshot.entry_count,
                "shared_budget_bytes": snapshot.shared_budget_bytes,
                "hits": snapshot.hits,
                "misses": snapshot.misses,
                "evictions": snapshot.evictions,
                "bypasses": snapshot.bypasses,
            },
            "databases": {
                database: {
                    "available": self.core.is_database_available(database),
                    "progress_fresh": self.lease_fresh(database, now),
                }
                for database in self.config.databases
            },
            "captures": len(self._handles),
            "connections": len(self._connections),
            "upstream_commands": self.progress.snapshot(),
            "counters": asdict(self.counters),
        }

    def _accept(self) -> None:
        assert self._listener is not None
        while True:
            try:
                sock, _address = self._listener.accept()
            except BlockingIOError:
                return
            if len(self._connections) >= self.config.limits.connections:
                self.counters.connections_rejected += 1
                sock.close()
                continue
            sock.settimeout(0.0)
            connection = _Connection(sock)
            self._connections[sock.fileno()] = connection
            self._selector.register(sock, selectors.EVENT_READ, connection)
            self.counters.connections_accepted += 1

    def detach(self, connection: _Connection) -> None:
        if connection.closed:
            return  # pragma: lax no cover (peer reset timing)
        connection.closed = True
        self._selector.unregister(connection.sock)
        del self._connections[connection.sock.fileno()]
        for handle_id in tuple(connection.handles):
            self._release(handle_id)
        connection.handles.clear()
        connection.outbox.clear()
        connection.sock.close()

    def _enqueue(self, connection: _Connection, reply: Message) -> bool:
        frame = encode_frame(reply)
        connection.queued += len(frame)
        connection.replies += 1
        self.counters.peak_queued_bytes = max(
            self.counters.peak_queued_bytes, connection.queued
        )
        if (
            connection.queued > self.config.limits.queued_bytes_per_connection
            or connection.replies > self.config.limits.requests_per_connection
        ):
            self.counters.detached += 1
            self.detach(connection)
            return False
        connection.outbox.append(memoryview(frame))
        return True

    def _flush(self, connection: _Connection) -> bool:
        while connection.outbox:
            view = connection.outbox[0]
            try:
                sent = connection.sock.send(view)
            except BlockingIOError:
                break
            except OSError:  # pragma: lax no cover (peer reset timing)
                self.detach(connection)
                return False
            self.counters.ipc_bytes_sent += sent
            connection.queued -= sent
            if sent == len(view):
                connection.outbox.popleft()
                connection.replies -= 1
            else:
                connection.outbox[0] = view[sent:]
                break
        wants_write = bool(connection.outbox)
        if wants_write != connection.writable:
            connection.writable = wants_write
            self._selector.modify(
                connection.sock,
                selectors.EVENT_READ | (selectors.EVENT_WRITE if wants_write else 0),
                connection,
            )
        return True

    def _receive(self, connection: _Connection, now: NonNegativeFloat) -> None:
        try:
            chunk = connection.sock.recv(_RECEIVE_BYTES)
        except BlockingIOError:  # pragma: no cover (selector reported readability)
            return
        except OSError:  # pragma: lax no cover (peer reset timing)
            self.detach(connection)
            return
        if not chunk:
            self.detach(connection)
            return
        self.counters.ipc_bytes_received += len(chunk)
        connection.inbox += chunk
        try:
            messages = self._frames(connection)
        except ProtocolError:
            self._reject(connection)
            return
        for message in messages:
            try:
                reply = self._reply(connection, message, now)
            except ProtocolError:
                self._reject(connection)
                return
            if reply is None:
                continue
            if not self._enqueue(connection, reply):
                return
            if reply["r"] == "error":
                self._flush(connection)
                self.detach(connection)
                return
        self._flush(connection)

    def _frames(self, connection: _Connection) -> list[Message]:
        inbox = connection.inbox
        messages: list[Message] = []
        offset = 0
        while len(inbox) - offset >= LENGTH_BYTES:
            header = bytes(inbox[offset : offset + LENGTH_BYTES])
            end = offset + LENGTH_BYTES + frame_length(header, self.config.frame_limit)
            if len(inbox) < end:
                break
            with memoryview(inbox) as view:
                messages.append(decode_frame(view[offset + LENGTH_BYTES : end]))
            offset = end
        del inbox[:offset]
        return messages

    def _reply(
        self, connection: _Connection, message: Message, now: NonNegativeFloat
    ) -> Message | None:
        try:
            reply = self._handle_request(connection, message, now)
        except KeyError as error:
            raise ProtocolError("frame is missing a required field") from error
        if reply is not None:
            reply["v"] = PROTOCOL_VERSION
            reply["id"] = message["id"]
        return reply

    def _reject(self, connection: _Connection) -> None:
        self.counters.protocol_errors += 1
        self.detach(connection)

    def serve(
        self, control: Connection, on_control: Callable[[Message], Message | None]
    ) -> None:
        self._selector.register(control.fileno(), selectors.EVENT_READ, control)
        next_sweep = 0.0
        while True:
            events = self._selector.select(timeout=_SWEEP_SECONDS)
            started = time.monotonic()
            if started < self._paused_until:
                time.sleep(self._paused_until - started)
                started = time.monotonic()
            for key, mask in events:
                source = key.data
                if source is None:
                    self._accept()
                elif isinstance(source, _Connection):
                    if mask & selectors.EVENT_READ:
                        self._receive(source, started)
                    if mask & selectors.EVENT_WRITE and not source.closed:
                        self._flush(source)
                else:
                    request = control.recv()
                    if request == "close":
                        return
                    control.send(on_control(request))
            if started >= next_sweep:
                self._sweep(started)
                next_sweep = started + _SWEEP_SECONDS
            self.counters.busy_seconds += time.monotonic() - started

    def pause(self, seconds: PositiveFloat) -> None:
        self._paused_until = time.monotonic() + seconds

    def close(self) -> None:
        if self._listener is not None:
            self._selector.unregister(self._listener)
            self._listener.close()
            self._listener = None
            pathlib.Path(self.config.socket_path).unlink(missing_ok=True)
        for connection in tuple(self._connections.values()):
            self.detach(connection)
        try:
            self.streams.close()
        finally:
            try:
                self.core.close()
            finally:
                self.client.close()
                if self._lock_file is not None:
                    self._lock_file.close()

    def lose_history(self, database: str) -> None:
        supervisor = self.streams._supervisors[database]
        supervisor_type = type(supervisor)
        original = supervisor_type._open_stream

        def unresumable(
            _instance: DatabaseStreamSupervisor,
            *,
            resume_token: Mapping[str, object] | None,  # noqa: ARG001
            use_start_after: bool,  # noqa: ARG001
        ) -> None:
            supervisor_type._open_stream = original  # type: ignore[method-assign]
            raise OperationFailure("history lost", code=_HISTORY_LOST)

        supervisor_type._open_stream = unresumable  # type: ignore[method-assign,assignment]
        stream = supervisor._stream
        assert stream is not None
        stream.close()


def _namespace(value: object) -> NamespaceId:
    if (
        not isinstance(value, list)
        or len(value) != 2
        or not all(isinstance(part, str) for part in value)
    ):
        raise ProtocolError("namespace must be a database/collection pair")
    return NamespaceId(value[0], value[1])
