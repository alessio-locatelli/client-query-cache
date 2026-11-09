from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, cast, override
from urllib.parse import urlsplit

import psutil
from pymongo.errors import OperationFailure

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.shared_cache.profiling import WindowProfiler
from client_query_cache._core.keys import NamespaceId
from client_query_cache._core.stream_events import CHANGE_STREAM_HISTORY_LOST_CODE
from client_query_cache._shared.coordinator import SharedCacheOwner
from client_query_cache._shared.wire import decode_key
from client_query_cache._types import NonNegativeFloat, NonNegativeInt, PositiveFloat

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from multiprocessing.connection import Connection

    from client_query_cache._shared.coordinator import (
        Message,
        OwnerConfig,
        _Connection,
    )
    from client_query_cache.synchronous.streams import DatabaseStreamSupervisor

TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)


class _GatedSocket:
    __slots__ = ("_running", "_socket")

    def __init__(self, destination: socket.socket, running: threading.Event) -> None:
        self._socket = destination
        self._running = running

    def sendall(self, chunk: bytes) -> None:
        self._running.wait()
        self._socket.sendall(chunk)


class FaultableProxy(DirectPathByteProxy):
    __slots__ = ("_running",)

    def __init__(self, config: DirectPathProxyConfig) -> None:
        super().__init__(config)
        self._running = threading.Event()
        self._running.set()

    @override
    def __exit__(self, *exc_info: object) -> None:
        self._running.set()
        super().__exit__(*exc_info)

    def pause(self) -> None:
        self._running.clear()

    def resume(self) -> None:
        self._running.set()

    def sever(self) -> None:
        with self._lock:
            sockets = tuple(self._sockets)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:  # pragma: lax no cover (connection teardown race)
                pass

    @override
    def _relay(
        self, source: socket.socket, destination: socket.socket, *, is_sent: bool
    ) -> None:
        gated = cast("socket.socket", _GatedSocket(destination, self._running))
        super()._relay(source, gated, is_sent=is_sent)


def proxy_for(uri: str) -> FaultableProxy:
    address = urlsplit(uri)
    assert address.hostname is not None
    assert address.port is not None
    return FaultableProxy(
        DirectPathProxyConfig(TOPOLOGY, address.hostname, address.port)
    )


def process_sample() -> Message:
    process = psutil.Process()
    cpu = process.cpu_times()
    memory = process.memory_full_info()
    return {
        "pid": process.pid,
        "cpu_seconds": cpu.user + cpu.system,
        "pss_bytes": memory.pss,
        "uss_bytes": memory.uss,
    }


_PROFILER = WindowProfiler()
_HISTORY_READY = threading.Event()


class PausableOwner(SharedCacheOwner):
    __slots__ = ("_resumes_at",)

    def __init__(self, config: OwnerConfig) -> None:
        super().__init__(config)
        self._resumes_at = 0.0

    def pause(self, seconds: PositiveFloat) -> NonNegativeFloat:
        self._resumes_at = time.monotonic() + seconds
        return self._resumes_at

    def _wait_if_paused(self, now: NonNegativeFloat) -> NonNegativeFloat:
        if now < self._resumes_at:
            time.sleep(self._resumes_at - now)
            return time.monotonic()
        return now

    @override
    def _accept(self) -> None:
        self._wait_if_paused(time.monotonic())
        super()._accept()

    @override
    def _flush(self, connection: _Connection) -> bool:
        self._wait_if_paused(time.monotonic())
        return super()._flush(connection)

    @override
    def _receive(self, connection: _Connection, now: NonNegativeFloat) -> None:
        super()._receive(connection, self._wait_if_paused(now))

    @override
    def _sweep(self, now: NonNegativeFloat) -> None:
        super()._sweep(self._wait_if_paused(now))

    @override
    def _drain_admissions(self, *, all_pending: bool = False) -> None:
        self._wait_if_paused(time.monotonic())
        super()._drain_admissions(all_pending=all_pending)


def pause_owner(owner: SharedCacheOwner, seconds: PositiveFloat) -> NonNegativeFloat:
    assert isinstance(owner, PausableOwner)
    return owner.pause(seconds)


def lose_history(owner: SharedCacheOwner, database: str) -> None:
    supervisor = owner.streams._supervisors[database]
    supervisor_type = type(supervisor)
    original = supervisor_type._open_stream

    def unresumable(
        _instance: DatabaseStreamSupervisor,
        *,
        resume_token: Mapping[str, object] | None,  # noqa: ARG001 - Keep the patched method's keyword signature.
        use_start_after: bool,  # noqa: ARG001 - Keep the patched method's keyword signature.
    ) -> None:
        supervisor_type._open_stream = original  # type: ignore[method-assign]
        raise OperationFailure("history lost", code=CHANGE_STREAM_HISTORY_LOST_CODE)

    supervisor_type._open_stream = unresumable  # type: ignore[method-assign,assignment]
    stream = supervisor._stream
    assert stream is not None
    stream.close()


def hold_history(owner: SharedCacheOwner) -> None:
    database = owner.config.databases[0]
    supervisor = owner.streams._supervisors[database]
    supervisor_type = type(supervisor)
    original = supervisor_type._open_stream
    _HISTORY_READY.clear()

    def blocked_open(
        instance: DatabaseStreamSupervisor,
        *,
        resume_token: Mapping[str, object] | None,
        use_start_after: bool,
    ) -> None:
        _HISTORY_READY.wait()
        supervisor_type._open_stream = original  # type: ignore[method-assign]
        original(instance, resume_token=resume_token, use_start_after=use_start_after)

    supervisor_type._open_stream = blocked_open  # type: ignore[method-assign,assignment]
    lose_history(owner, database)


def activation_pending(owner: SharedCacheOwner) -> bool:
    with owner._activation_lock:
        return any(state == "pending" for state, _since in owner._activation.values())


class _RacingShape:
    __slots__ = ("_action", "_value")

    def __init__(self, value: object, action: Callable[[], object]) -> None:
        self._value = value
        self._action: Callable[[], object] | None = action

    def __hash__(self) -> int:
        action, self._action = self._action, None
        if action is not None:
            action()
        return hash(self._value)

    def __ne__(self, other: object) -> bool:
        return other is not self


def race_next_admission(owner: SharedCacheOwner, race: str) -> None:
    original = SharedCacheOwner._admit

    def racing(
        instance: SharedCacheOwner,
        connection: _Connection,
        message: Message,
        now: NonNegativeFloat,
    ) -> None:
        SharedCacheOwner._admit = original  # type: ignore[method-assign]
        handle = instance._handles[cast("bytes", message["handle"])]
        namespace = handle.capture.namespace
        shape = handle.shape
        if race == "write":
            identity = decode_key(cast("bytes", handle.identity_key))
            handle.shape = _RacingShape(
                shape, lambda: owner.core.record_write(namespace, identity)
            )
            original(instance, connection, message, now)
            return
        original(instance, connection, message, now)
        half_entry = owner.config.max_entry_bytes // 2
        filler = {"filler": "x" * half_entry}
        for offset in range(owner.config.budget_bytes // half_entry + 1):
            capture = owner.core.begin_identity_admission(
                namespace, f"race-filler-{offset}"
            )
            owner.core.admit_identity(capture, shape, filler)

    SharedCacheOwner._admit = racing  # type: ignore[method-assign,assignment]


def _sample(owner: SharedCacheOwner, proxy: FaultableProxy) -> Message:
    database = owner.config.databases[0]
    telemetry = owner.core.stream_cost_snapshot(database)
    return {
        **process_sample(),
        "monotonic": time.monotonic(),
        "observation": owner.observation(time.monotonic()),
        "commands": owner.progress.snapshot(),
        "wire_sent": proxy.bytes_sent,
        "wire_received": proxy.bytes_received,
        "invalidations": telemetry.invalidations,
        "lag_windows": telemetry.invalidation_lag_windows,
        "apply_readings": [
            asdict(reading) for reading in telemetry.invalidation_apply_readings
        ],
        "health": owner.streams.stream_health_snapshot(database).status.value,
        "activation_pending": activation_pending(owner),
    }


_CONTROL: dict[str, Callable[[SharedCacheOwner, FaultableProxy, Message], object]] = {
    "invalidate": lambda owner, _proxy, request: owner.core.record_write(
        NamespaceId(owner.config.databases[0], cast("str", request["collection"])),
        request["key"],
    ),
    "reset": lambda owner, _proxy, _request: owner.core.reset_stream_cost_statistics(
        owner.config.databases[0]
    ),
    "pause-server": lambda owner, _proxy, request: pause_owner(
        owner, cast("float", request["seconds"])
    ),
    "pause-watch": lambda _owner, proxy, _request: proxy.pause(),
    "resume-watch": lambda _owner, proxy, _request: proxy.resume(),
    "sever": lambda _owner, proxy, _request: proxy.sever(),
    "lose-history": lambda owner, _proxy, _request: lose_history(
        owner, owner.config.databases[0]
    ),
    "hold-history": lambda owner, _proxy, _request: hold_history(owner),
    "resume-history": lambda _owner, _proxy, _request: _HISTORY_READY.set(),
    "race-admission": lambda owner, _proxy, request: race_next_admission(
        owner, cast("str", request["race"])
    ),
    "profile-start": lambda _owner, _proxy, _request: _PROFILER.start(),
    "profile-stop": lambda _owner, _proxy, _request: _PROFILER.stop("owner"),
}


def _control(
    owner: SharedCacheOwner, proxy: FaultableProxy, request: Message
) -> Message:
    operation = cast("str", request["op"])
    if operation == "sample":
        return _sample(owner, proxy)
    outcome = _CONTROL[operation](owner, proxy, request)
    if operation == "pause-server":
        return {"ok": True, "resumes_at": outcome}
    return {"ok": True}


class _ControlChannel:
    __slots__ = ("_connection", "_owner", "_proxy")

    def __init__(
        self, owner: SharedCacheOwner, proxy: FaultableProxy, connection: Connection
    ) -> None:
        self._owner = owner
        self._proxy = proxy
        self._connection = connection

    def fileno(self) -> NonNegativeInt:
        return self._connection.fileno()

    def recv(self) -> Message | str:
        request: Message | str = self._connection.recv()
        if request != "close":
            # A startup sample must include all frames posted before workers
            # announced readiness, including the last unswept batch.
            limits = self._owner.config.shared_index
            if limits is not None and limits.native_admission_queue:
                self._owner._drain_admissions(all_pending=True)
            self._connection.send(
                _control(self._owner, self._proxy, cast("Message", request))
            )
        return request


def owner_main(config: OwnerConfig, control: Connection) -> None:
    with proxy_for(config.mongodb_uri) as proxy:
        owner = PausableOwner(
            replace(config, mongodb_uri=f"mongodb://127.0.0.1:{proxy.local_port}")
        )
        try:
            owner.bind()
            control.send({"kind": "ready", "pid": os.getpid(), **process_sample()})
            owner.serve(cast("Connection", _ControlChannel(owner, proxy, control)))
        except RuntimeError as error:
            control.send({"kind": "failure", "error": str(error)})
        finally:
            _HISTORY_READY.set()
            proxy.resume()
            owner.close()
            try:
                control.send({"kind": "closed"})
            except BrokenPipeError:
                pass
            control.close()
