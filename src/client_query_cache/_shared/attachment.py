from __future__ import annotations

import asyncio
import errno
import os
import socket
import threading
import time
import weakref
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Final

from client_query_cache._core.errors import CacheClosedError, CacheConfigurationError
from client_query_cache._shared.wire import (
    LENGTH_BYTES,
    PROTOCOL_VERSION,
    ProtocolError,
    decode_frame,
    encode_frame,
    frame_length,
)
from client_query_cache._shared_index import ReaderIndex
from client_query_cache._types import (
    MaxAwaitTimeMs,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)
from client_query_cache.asynchronous.streams import _join_cleanup

if TYPE_CHECKING:
    from collections.abc import Callable


type Message = dict[str, object]

_RETRY_SECONDS: Final = 0.1
_RECEIVE_BYTES: Final = 262_144
_ATTACH_DEADLINE_SECONDS: Final = 5.0
_LOST: Final[Message] = {"r": "lost"}
_CONTROL_DESCRIPTORS: Final = 2
_MAX_DESCRIPTORS: Final = 4


class InheritedAttachmentError(CacheClosedError):
    pass


class AttachmentConfigurationError(CacheConfigurationError):
    pass


def attachment_unavailable(error: OSError) -> bool:
    return isinstance(error, (ConnectionError, FileNotFoundError, TimeoutError)) or (
        error.errno in {errno.EAGAIN, errno.ENOTCONN}
    )


@dataclass(frozen=True, slots=True)
class AttachmentConfig:
    socket_path: str
    capability: bytes = field(repr=False)
    budget_bytes: PositiveInt
    max_entry_bytes: PositiveInt
    max_await_time_ms: MaxAwaitTimeMs
    rpc_deadline_seconds: PositiveFloat
    frame_limit: PositiveInt
    max_namespaces: PositiveInt = 1024

    def hello(self, role: str | None = None) -> Message:
        message: Message = {
            "v": PROTOCOL_VERSION,
            "id": 0,
            "op": "hello",
            "capability": self.capability,
            "pid": os.getpid(),
            "budget_bytes": self.budget_bytes,
            "max_entry_bytes": self.max_entry_bytes,
            "max_await_time_ms": self.max_await_time_ms,
        }
        if role is not None:
            message["role"] = role
        return message


@dataclass(slots=True)
class EndpointCounters:
    requests: NonNegativeInt = 0
    timeouts: NonNegativeInt = 0
    failures: NonNegativeInt = 0
    connects: NonNegativeInt = 0
    late_replies: NonNegativeInt = 0
    one_way: NonNegativeInt = 0
    native_admissions: NonNegativeInt = 0
    native_admission_drops: NonNegativeInt = 0
    native_admission_recoveries: NonNegativeInt = 0
    dropped_one_way: NonNegativeInt = 0
    bytes_sent: NonNegativeInt = 0
    bytes_received: NonNegativeInt = 0


@dataclass(slots=True)
class AdmissionRecovery:
    awaiting_capacity: bool = False
    fallback_until: NonNegativeFloat = 0.0
    generation: NonNegativeInt = 0
    _lock: threading.Lock = field(
        default_factory=threading.Lock, repr=False, compare=False
    )

    def dropped(self) -> None:
        with self._lock:
            self.generation += 1
            self.awaiting_capacity = True
            self.fallback_until = 0.0

    def enqueued(self, generation: NonNegativeInt) -> bool:
        with self._lock:
            if not self.awaiting_capacity or generation != self.generation:
                return False
            self.awaiting_capacity = False
            self.fallback_until = time.monotonic() + _RETRY_SECONDS
            return True

    @property
    def active(self) -> bool:
        with self._lock:
            if self.fallback_until:
                if time.monotonic() < self.fallback_until:
                    return True
                self.fallback_until = 0.0
            return False


def _one_way_frame(
    message: Message,
    config: AttachmentConfig,
    counters: EndpointCounters,
    reader: ReaderIndex | None,
    recovery: AdmissionRecovery,
) -> tuple[bytes, PositiveInt] | None:
    message["v"] = PROTOCOL_VERSION
    message["id"] = 0
    frame = encode_frame(message)
    frame_bytes = len(frame)
    if frame_bytes - LENGTH_BYTES > config.frame_limit:
        counters.dropped_one_way += 1
        return None
    if reader is not None:
        generation = recovery.generation if recovery.awaiting_capacity else None
        if reader.enqueue_admission(frame):
            counters.native_admissions += 1
            if generation is not None and recovery.enqueued(generation):
                counters.native_admission_recoveries += 1
            counters.one_way += 1
            counters.bytes_sent += frame_bytes
            return None
    return frame, frame_bytes


def _accepted(reply: Message) -> Message:
    if reply["r"] == "error":
        message = f"shared cache owner rejected the attachment: {reply['reason']}"
        raise AttachmentConfigurationError(message)
    return reply


@dataclass(frozen=True, slots=True)
class ControlAttachment:
    sock: socket.socket
    reader: ReaderIndex


def _handshake_reply(
    sock: socket.socket, config: AttachmentConfig, received: list[int]
) -> Message:
    deadline = time.monotonic() + _ATTACH_DEADLINE_SECONDS
    inbox = bytearray()
    end: int | None = None
    while end is None or len(inbox) < end:
        sock.settimeout(max(deadline - time.monotonic(), 0.000001))
        data, descriptors, flags, _address = socket.recv_fds(
            sock, _RECEIVE_BYTES, _MAX_DESCRIPTORS, socket.MSG_CMSG_CLOEXEC
        )
        received.extend(descriptors)
        if flags & socket.MSG_CTRUNC:
            raise ProtocolError("handshake descriptors were truncated")
        if not data:
            raise ConnectionResetError("owner closed the attachment")
        inbox += data
        if end is None and len(inbox) >= LENGTH_BYTES:
            header = bytes(inbox[:LENGTH_BYTES])
            end = LENGTH_BYTES + frame_length(header, config.frame_limit)
    if len(inbox) != end:
        raise ProtocolError("the owner sent data after the handshake reply")
    return _accepted(decode_frame(bytes(inbox[LENGTH_BYTES:end])))


def _reader(received: list[int], reply: Message) -> ReaderIndex:
    if len(received) != _CONTROL_DESCRIPTORS:
        raise ProtocolError("the handshake carries exactly two descriptors")
    reader = ReaderIndex(received[0], received[1])
    if reader.incarnation != reply["incarnation"]:
        raise ProtocolError("the index belongs to another owner incarnation")
    return reader


def control_handshake(config: AttachmentConfig) -> ControlAttachment:
    sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    received: list[int] = []
    try:
        sock.settimeout(_ATTACH_DEADLINE_SECONDS)
        sock.connect(config.socket_path)
        sock.sendall(encode_frame(config.hello(role="control")))
        reader = _reader(received, _handshake_reply(sock, config, received))
    except BaseException:
        sock.close()
        raise
    finally:
        for descriptor in received:
            os.close(descriptor)
    return ControlAttachment(sock, reader)


_LOCAL_INDEXES: Final[weakref.WeakSet[LocalIndex | AsyncLocalIndex]] = weakref.WeakSet()


def _unregister_closed(local: LocalIndex | AsyncLocalIndex) -> None:
    if local.descriptor < 0:
        _LOCAL_INDEXES.discard(local)


# Fork callbacks run before coverage resumes in the child.
def _detach_inherited() -> None:  # pragma: lax no cover
    for local in tuple(_LOCAL_INDEXES):
        local.reader.detach()
        descriptor = local.descriptor
        if descriptor < 0:
            continue
        placeholder = os.open(os.devnull, os.O_RDONLY | os.O_CLOEXEC)
        os.dup2(placeholder, descriptor)
        os.close(placeholder)


os.register_at_fork(after_in_child=_detach_inherited)


class LocalIndex:
    __slots__ = (
        "__weakref__",
        "_sock",
        "_watcher",
        "admissions_enabled",
        "incarnation",
        "reader",
    )

    def __init__(self, control: ControlAttachment) -> None:
        self.reader = control.reader
        self.admissions_enabled = control.reader.admissions_enabled
        self.incarnation = control.reader.incarnation
        self._sock = control.sock
        self._sock.settimeout(None)
        self._watcher = threading.Thread(target=self._watch, daemon=True)
        _LOCAL_INDEXES.add(self)
        self._watcher.start()

    @property
    def descriptor(self) -> int:
        return self._sock.fileno()

    @classmethod
    def attach(cls, config: AttachmentConfig) -> LocalIndex:
        return cls(control_handshake(config))

    def _watch(self) -> None:
        try:
            self._sock.recv(1)
        except OSError:  # pragma: lax no cover (peer reset timing)
            pass
        finally:
            self.reader.detach()

    def close(self) -> None:
        try:
            try:
                self._sock.shutdown(socket.SHUT_RDWR)
            except OSError:  # pragma: lax no cover (owner exit timing)
                pass
            self._watcher.join()
        finally:
            try:
                self._sock.close()
            finally:
                _unregister_closed(self)


class AsyncLocalIndex:
    __slots__ = (
        "__weakref__",
        "_sock",
        "_watcher",
        "_writer",
        "admissions_enabled",
        "incarnation",
        "reader",
    )

    def __init__(
        self,
        reader: ReaderIndex,
        stream: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        sock: socket.socket,
    ) -> None:
        self.reader = reader
        self.admissions_enabled = reader.admissions_enabled
        self.incarnation = reader.incarnation
        self._sock = sock
        self._writer = writer
        self._watcher = asyncio.create_task(self._watch(stream))
        _LOCAL_INDEXES.add(self)

    @property
    def descriptor(self) -> int:
        return self._sock.fileno()

    @classmethod
    async def attach(cls, config: AttachmentConfig) -> AsyncLocalIndex:
        handshake = asyncio.create_task(asyncio.to_thread(control_handshake, config))
        try:
            control = await _join_cleanup(handshake)
        except asyncio.CancelledError:
            handshake.result().sock.close()
            raise
        try:
            stream, writer = await asyncio.open_unix_connection(sock=control.sock)
        except BaseException:
            control.sock.close()
            raise
        return cls(control.reader, stream, writer, control.sock)

    async def _watch(self, stream: asyncio.StreamReader) -> None:
        try:
            await stream.read(1)
        except OSError:  # pragma: lax no cover (owner exit timing)
            pass
        finally:
            self.reader.detach()

    async def close(self) -> None:
        self.reader.detach()
        self._writer.close()
        self._watcher.cancel()
        try:
            try:
                await self._watcher
            except asyncio.CancelledError:
                pass
        finally:
            try:
                await self._writer.wait_closed()
            finally:
                _unregister_closed(self)


class _SyncConnection:
    __slots__ = ("inbox", "next_id", "sock")

    def __init__(self, sock: socket.socket) -> None:
        self.sock = sock
        self.inbox = bytearray()
        self.next_id = 1

    def receive(
        self, deadline: NonNegativeFloat, limit: PositiveInt, counters: EndpointCounters
    ) -> Message:
        while True:
            if len(self.inbox) >= LENGTH_BYTES:
                end = LENGTH_BYTES + frame_length(
                    bytes(self.inbox[:LENGTH_BYTES]), limit
                )
                if len(self.inbox) >= end:
                    message = decode_frame(bytes(self.inbox[LENGTH_BYTES:end]))
                    del self.inbox[:end]
                    return message
            self.sock.settimeout(max(deadline - time.monotonic(), 0.000001))
            chunk = self.sock.recv(_RECEIVE_BYTES)
            if not chunk:
                raise ConnectionResetError("owner closed the attachment")
            counters.bytes_received += len(chunk)
            self.inbox += chunk


class _Lease:
    __slots__ = ("connection", "release")

    def __init__(
        self, connection: _SyncConnection, release: Callable[[_SyncConnection], None]
    ) -> None:
        self.connection = connection
        self.release = release

    def __del__(self) -> None:
        self.release(self.connection)


class SyncEndpoint:
    __slots__ = (
        "_closed",
        "_connections",
        "_local",
        "_lock",
        "_pid",
        "_retry_after",
        "admission_recovery",
        "config",
        "counters",
        "incarnation",
    )

    def __init__(self, config: AttachmentConfig, *, require_owner: bool = True) -> None:
        self.config = config
        self._pid = os.getpid()
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: set[_SyncConnection] = set()
        self._retry_after = 0.0
        self._closed = False
        self.counters = EndpointCounters()
        self.admission_recovery = AdmissionRecovery()
        self.incarnation: object = None
        deadline = (
            _ATTACH_DEADLINE_SECONDS if require_owner else config.rpc_deadline_seconds
        )
        if self._connect(time.monotonic() + deadline) is None and require_owner:
            message = "shared cache owner is not reachable"
            raise AttachmentConfigurationError(message)

    def _check_owner(self) -> None:
        if os.getpid() != self._pid:
            message = "attachment was inherited from another process"
            raise InheritedAttachmentError(message)

    def _connect(self, deadline: NonNegativeFloat) -> _SyncConnection | None:
        sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        connection = _SyncConnection(sock)
        try:
            reply = self._handshake(connection, deadline)
        except OSError as error:
            sock.close()
            if not attachment_unavailable(error):
                raise
            self._retry_after = time.monotonic() + _RETRY_SECONDS
            self.counters.failures += 1
            return None
        except BaseException:
            sock.close()
            raise
        try:
            _accepted(reply)
        except AttachmentConfigurationError:
            sock.close()
            raise
        self.counters.connects += 1
        self.incarnation = reply["incarnation"]
        with self._lock:
            self._connections.add(connection)
        self._local.lease = _Lease(connection, self._release)
        return connection

    def _release(self, connection: _SyncConnection) -> None:
        connection.sock.close()
        with self._lock:
            self._connections.discard(connection)

    def _leased(self) -> _SyncConnection | None:
        try:
            lease: _Lease | None = self._local.lease
        except AttributeError:
            return None
        return None if lease is None else lease.connection

    @property
    def connected(self) -> bool:
        return not self._closed and self._leased() is not None

    def _handshake(
        self, connection: _SyncConnection, deadline: NonNegativeFloat
    ) -> Message:
        connection.sock.settimeout(max(deadline - time.monotonic(), 0.000001))
        connection.sock.connect(self.config.socket_path)
        frame = encode_frame(self.config.hello())
        connection.sock.sendall(frame)
        self.counters.bytes_sent += len(frame)
        return connection.receive(deadline, self.config.frame_limit, self.counters)

    def _current(self, deadline: NonNegativeFloat) -> _SyncConnection | None:
        connection = self._leased()
        if connection is not None:
            return connection
        if self._closed or time.monotonic() < self._retry_after:
            return None
        return self._connect(deadline)

    def _drop(self) -> None:
        self._local.lease = None
        self._retry_after = time.monotonic() + _RETRY_SECONDS

    def request(self, message: Message) -> Message | None:
        self._check_owner()
        deadline = time.monotonic() + self.config.rpc_deadline_seconds
        connection = self._current(deadline)
        if connection is None:
            return None
        self.counters.requests += 1
        message["v"] = PROTOCOL_VERSION
        message["id"] = connection.next_id
        connection.next_id += 1
        frame = encode_frame(message)
        try:
            connection.sock.settimeout(max(deadline - time.monotonic(), 0.000001))
            connection.sock.sendall(frame)
            self.counters.bytes_sent += len(frame)
            return connection.receive(deadline, self.config.frame_limit, self.counters)
        except TimeoutError:
            self.counters.timeouts += 1
        except OSError:
            self.counters.failures += 1
        self._drop()
        return None

    def send(self, message: Message, reader: ReaderIndex | None = None) -> None:
        self._check_owner()
        if self._closed:
            self.counters.dropped_one_way += 1
            return
        prepared = None
        if reader is not None and reader.admissions_enabled:
            prepared = _one_way_frame(
                message, self.config, self.counters, reader, self.admission_recovery
            )
            if prepared is None:
                return
        connection = self._leased()
        if connection is None:
            self.counters.dropped_one_way += 1
            if prepared is not None:
                self.counters.native_admission_drops += 1
                self.admission_recovery.dropped()
            return
        if prepared is None:
            prepared = _one_way_frame(
                message, self.config, self.counters, reader, self.admission_recovery
            )
            if prepared is None:
                return
        frame, frame_bytes = prepared
        try:
            connection.sock.settimeout(self.config.rpc_deadline_seconds)
            connection.sock.sendall(frame)
        except OSError:
            self.counters.dropped_one_way += 1
            self._drop()
            return
        self.counters.one_way += 1
        self.counters.bytes_sent += frame_bytes

    def close(self) -> None:
        with self._lock:
            self._closed = True
            connections = tuple(self._connections)
            self._connections.clear()
        for connection in connections:
            connection.sock.close()


class AsyncEndpoint:
    __slots__ = (
        "_closed",
        "_connect_lock",
        "_pending",
        "_pid",
        "_reader_task",
        "_retry_after",
        "_writer",
        "admission_recovery",
        "config",
        "counters",
        "incarnation",
        "next_id",
    )

    def __init__(self, config: AttachmentConfig) -> None:
        self.config = config
        self._pid = os.getpid()
        self._connect_lock = asyncio.Lock()
        self._closed = False
        self._pending: dict[
            NonNegativeInt, tuple[asyncio.StreamWriter, asyncio.Future[Message]]
        ] = {}
        self._writer: asyncio.StreamWriter | None = None
        self._reader_task: asyncio.Task[None] | None = None
        self._retry_after = 0.0
        self.counters = EndpointCounters()
        self.admission_recovery = AdmissionRecovery()
        self.incarnation: object = None
        self.next_id = 1

    @classmethod
    async def attach(
        cls, config: AttachmentConfig, *, require_owner: bool = True
    ) -> AsyncEndpoint:
        endpoint = cls(config)
        deadline = (
            _ATTACH_DEADLINE_SECONDS if require_owner else config.rpc_deadline_seconds
        )
        try:
            async with asyncio.timeout(deadline):
                connected = await endpoint._connect()
        except TimeoutError:
            if require_owner:
                raise
            connected = endpoint._unreachable()
        if not connected and require_owner:
            message = "shared cache owner is not reachable"
            raise AttachmentConfigurationError(message)
        return endpoint

    def _check_owner(self) -> None:
        if os.getpid() != self._pid:
            message = "attachment was inherited from another process"
            raise InheritedAttachmentError(message)

    async def _connect(self) -> bool:
        async with self._connect_lock:
            if self._writer is not None:
                return True
            if self._closed or time.monotonic() < self._retry_after:
                return False
            try:
                reader, writer = await asyncio.open_unix_connection(
                    self.config.socket_path, limit=self.config.frame_limit * 2
                )
            except OSError as error:
                if not attachment_unavailable(error):
                    raise
                return self._unreachable()
            frame = encode_frame(self.config.hello())
            writer.write(frame)
            self.counters.bytes_sent += len(frame)
            try:
                reply = _accepted(await self._read_frame(reader))
            except asyncio.IncompleteReadError:
                writer.close()
                return self._unreachable()
            except OSError as error:
                writer.close()
                if not attachment_unavailable(error):
                    raise
                return self._unreachable()
            except BaseException:
                writer.close()
                raise
            return self._install(reader, writer, reply)

    def _unreachable(self) -> bool:
        self._retry_after = time.monotonic() + _RETRY_SECONDS
        self.counters.failures += 1
        return False

    def _install(
        self,
        reader: asyncio.StreamReader,
        writer: asyncio.StreamWriter,
        reply: Message,
    ) -> bool:
        if self._closed:
            writer.close()
            return False
        self.counters.connects += 1
        self.incarnation = reply["incarnation"]
        self._writer = writer
        self._reader_task = asyncio.create_task(self._read_loop(reader, writer))
        return True

    async def _read_frame(self, reader: asyncio.StreamReader) -> Message:
        header = await reader.readexactly(LENGTH_BYTES)
        body = await reader.readexactly(frame_length(header, self.config.frame_limit))
        self.counters.bytes_received += LENGTH_BYTES + len(body)
        return decode_frame(body)

    async def _read_loop(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            while True:
                self._dispatch(await self._read_frame(reader))
        except asyncio.IncompleteReadError:
            pass
        except ConnectionResetError:  # pragma: lax no cover (peer reset timing)
            pass
        except BrokenPipeError:
            pass
        finally:
            self._abandon(writer)

    def _dispatch(self, message: Message) -> None:
        request_id = message["id"]
        assert isinstance(request_id, int)
        try:
            _writer, future = self._pending.pop(request_id)
        except KeyError:
            pass
        else:
            if not future.done():
                future.set_result(message)
                return
        self.counters.late_replies += 1
        if message["r"] == "miss" and message["handle"] is not None:
            self.send({"op": "discard", "handle": message["handle"]})

    def _abandon(self, writer: asyncio.StreamWriter) -> None:
        if self._writer is writer:
            self._writer = None
            self._retry_after = time.monotonic() + _RETRY_SECONDS
        writer.close()
        lost = [
            request_id
            for request_id, (sent_on, _future) in self._pending.items()
            if sent_on is writer
        ]
        for request_id in lost:
            _writer, future = self._pending.pop(request_id)
            if not future.done():
                future.set_result(_LOST)

    @property
    def connected(self) -> bool:
        return self._writer is not None and not self._writer.is_closing()

    async def request(self, message: Message) -> Message | None:
        self._check_owner()
        request_id = self.next_id
        self.next_id += 1
        future: asyncio.Future[Message] = asyncio.get_running_loop().create_future()
        try:
            async with asyncio.timeout(self.config.rpc_deadline_seconds):
                reply = await self._exchange(request_id, message, future)
        except TimeoutError:
            self.counters.timeouts += 1
            self._retry_after = time.monotonic() + _RETRY_SECONDS
            if self._writer is not None:
                self._abandon(self._writer)
            return None
        finally:
            try:
                del self._pending[request_id]
            except KeyError:
                pass
        if reply is _LOST:
            self.counters.failures += 1
            return None
        return reply

    async def _exchange(
        self,
        request_id: NonNegativeInt,
        message: Message,
        future: asyncio.Future[Message],
    ) -> Message | None:
        if not await self._connect():
            return None
        writer = self._writer
        assert writer is not None
        self.counters.requests += 1
        message["v"] = PROTOCOL_VERSION
        message["id"] = request_id
        frame = encode_frame(message)
        self._pending[request_id] = (writer, future)
        writer.write(frame)
        self.counters.bytes_sent += len(frame)
        return await future

    def send(self, message: Message, reader: ReaderIndex | None = None) -> None:
        self._check_owner()
        if self._closed:
            self.counters.dropped_one_way += 1
            return
        prepared = None
        if reader is not None and reader.admissions_enabled:
            prepared = _one_way_frame(
                message, self.config, self.counters, reader, self.admission_recovery
            )
            if prepared is None:
                return
        writer = self._writer
        if writer is None:
            self.counters.dropped_one_way += 1
            if prepared is not None:
                self.counters.native_admission_drops += 1
                self.admission_recovery.dropped()
            return
        if prepared is None:
            prepared = _one_way_frame(
                message, self.config, self.counters, reader, self.admission_recovery
            )
            if prepared is None:
                return
        frame, frame_bytes = prepared
        if (
            writer.transport.get_write_buffer_size() + frame_bytes
            > self.config.frame_limit + LENGTH_BYTES
        ):
            self.counters.dropped_one_way += 1
            if reader is not None and reader.admissions_enabled:
                self.counters.native_admission_drops += 1
                self.admission_recovery.dropped()
            if "handle" in message:
                writer.transport.abort()
                self._abandon(writer)
            return
        writer.write(frame)
        self.counters.one_way += 1
        self.counters.bytes_sent += frame_bytes

    async def close(self) -> None:
        self._closed = True
        writer = self._writer
        if writer is not None:
            self._abandon(writer)
        if self._reader_task is not None:
            self._reader_task.cancel()
            try:
                await self._reader_task
            except asyncio.CancelledError:
                pass
