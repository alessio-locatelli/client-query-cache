from __future__ import annotations

import asyncio
import os
import socket
import threading
import time
from dataclasses import dataclass
from typing import TYPE_CHECKING, Final

from benchmarks.stream_cost.shared_cache.wire import (
    LENGTH_BYTES,
    PROTOCOL_VERSION,
    decode_frame,
    encode_frame,
    frame_length,
)
from client_query_cache._types import (
    MaxAwaitTimeMs,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveFloat,
    PositiveInt,
)

if TYPE_CHECKING:
    from collections.abc import Callable


type Message = dict[str, object]

_RETRY_SECONDS: Final = 0.1
_RECEIVE_BYTES: Final = 262_144
_ATTACH_DEADLINE_SECONDS: Final = 5.0
_LOST: Final[Message] = {"r": "lost"}


class InheritedAttachmentError(RuntimeError):
    pass


class AttachmentConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class AttachmentConfig:
    socket_path: str
    capability: bytes
    budget_bytes: PositiveInt
    max_entry_bytes: PositiveInt
    max_await_time_ms: MaxAwaitTimeMs
    rpc_deadline_seconds: PositiveFloat
    frame_limit: PositiveInt

    def hello(self) -> Message:
        return {
            "v": PROTOCOL_VERSION,
            "id": 0,
            "op": "hello",
            "capability": self.capability,
            "pid": os.getpid(),
            "budget_bytes": self.budget_bytes,
            "max_entry_bytes": self.max_entry_bytes,
            "max_await_time_ms": self.max_await_time_ms,
        }


@dataclass(slots=True)
class EndpointCounters:
    requests: NonNegativeInt = 0
    timeouts: NonNegativeInt = 0
    failures: NonNegativeInt = 0
    connects: NonNegativeInt = 0
    late_replies: NonNegativeInt = 0
    one_way: NonNegativeInt = 0
    dropped_one_way: NonNegativeInt = 0
    bytes_sent: NonNegativeInt = 0
    bytes_received: NonNegativeInt = 0


def _accepted(reply: Message) -> Message:
    if reply["r"] == "error":
        message = f"shared cache owner rejected the attachment: {reply['reason']}"
        raise AttachmentConfigurationError(message)
    return reply


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
        "config",
        "counters",
        "incarnation",
    )

    def __init__(self, config: AttachmentConfig) -> None:
        self.config = config
        self._pid = os.getpid()
        self._local = threading.local()
        self._lock = threading.Lock()
        self._connections: set[_SyncConnection] = set()
        self._retry_after = 0.0
        self._closed = False
        self.counters = EndpointCounters()
        self.incarnation: object = None
        if self._connect(time.monotonic() + _ATTACH_DEADLINE_SECONDS) is None:
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
        except OSError:
            sock.close()
            self._retry_after = time.monotonic() + _RETRY_SECONDS
            self.counters.failures += 1
            return None
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

    def send(self, message: Message) -> None:
        self._check_owner()
        connection = self._leased()
        if connection is None:
            self.counters.dropped_one_way += 1
            return
        message["v"] = PROTOCOL_VERSION
        message["id"] = 0
        frame = encode_frame(message)
        try:
            connection.sock.settimeout(self.config.rpc_deadline_seconds)
            connection.sock.sendall(frame)
        except OSError:
            self.counters.dropped_one_way += 1
            self._drop()
            return
        self.counters.one_way += 1
        self.counters.bytes_sent += len(frame)

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
        self.incarnation: object = None
        self.next_id = 1

    @classmethod
    async def attach(cls, config: AttachmentConfig) -> AsyncEndpoint:
        endpoint = cls(config)
        async with asyncio.timeout(_ATTACH_DEADLINE_SECONDS):
            connected = await endpoint._connect()
        if not connected:
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
            except OSError:
                return self._unreachable()
            frame = encode_frame(self.config.hello())
            writer.write(frame)
            self.counters.bytes_sent += len(frame)
            try:
                reply = _accepted(await self._read_frame(reader))
            except asyncio.IncompleteReadError:
                writer.close()
                return self._unreachable()
            except ConnectionResetError:
                writer.close()
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

    def send(self, message: Message) -> None:
        self._check_owner()
        writer = self._writer
        if writer is None:
            self.counters.dropped_one_way += 1
            return
        message["v"] = PROTOCOL_VERSION
        message["id"] = 0
        frame = encode_frame(message)
        writer.write(frame)
        self.counters.one_way += 1
        self.counters.bytes_sent += len(frame)

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
