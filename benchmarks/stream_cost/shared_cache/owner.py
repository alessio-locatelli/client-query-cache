from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, cast, override
from urllib.parse import urlsplit

import psutil

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.shared_cache.coordinator import SharedCacheOwner
from benchmarks.stream_cost.shared_cache.profiling import WindowProfiler
from client_query_cache._core.keys import IdentityCacheKey, NamespaceId
from client_query_cache._core.lru import WeightedLru

if TYPE_CHECKING:
    from collections.abc import Callable, Mapping
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.coordinator import Message, OwnerConfig
    from client_query_cache._core.entries import CacheEntry
    from client_query_cache._core.keys import CacheKey
    from client_query_cache.synchronous.streams import DatabaseStreamSupervisor

TOPOLOGY = BenchmarkClientTopologyConfig(
    tls_enabled=False,
    compressor=WireCompressor.NONE,
    discovery_enabled=False,
    shared_connections=False,
)


class FaultableProxy(DirectPathByteProxy):
    __slots__ = ("_open",)

    def __init__(self, config: DirectPathProxyConfig) -> None:
        super().__init__(config)
        self._open = threading.Event()
        self._open.set()

    def pause(self) -> None:
        self._open.clear()

    def resume(self) -> None:
        self._open.set()

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
        while True:
            chunk = source.recv(65_536)
            if not chunk:
                return
            self._open.wait()
            destination.sendall(chunk)
            with self._lock:
                if is_sent:
                    self._bytes_sent += len(chunk)
                else:
                    self._bytes_received += len(chunk)


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


def hold_history(owner: SharedCacheOwner) -> None:
    database = owner.config.databases[0]
    supervisor = owner.streams._supervisors[database]  # noqa: SLF001
    supervisor_type = type(supervisor)
    original = supervisor_type._open_stream  # noqa: SLF001
    _HISTORY_READY.clear()

    def blocked_open(
        instance: DatabaseStreamSupervisor,
        *,
        resume_token: Mapping[str, object] | None,
        use_start_after: bool,
    ) -> None:
        _HISTORY_READY.wait()
        supervisor_type._open_stream = original  # type: ignore[method-assign]  # noqa: SLF001
        original(instance, resume_token=resume_token, use_start_after=use_start_after)

    supervisor_type._open_stream = blocked_open  # type: ignore[method-assign,assignment]  # noqa: SLF001
    owner.lose_history(database)


def activation_pending(owner: SharedCacheOwner) -> bool:
    with owner._activation_lock:  # noqa: SLF001
        return any(state == "pending" for state, _since in owner._activation.values())  # noqa: SLF001


def race_next_admission(owner: SharedCacheOwner, race: str) -> None:
    original = WeightedLru.conditional_put

    def racing(
        lru: WeightedLru, key: CacheKey, entry: CacheEntry
    ) -> tuple[bool, CacheEntry | None, list[CacheEntry]]:
        WeightedLru.conditional_put = original  # type: ignore[method-assign]
        put = original(lru, key, entry)
        assert isinstance(key, IdentityCacheKey)
        if race == "write":
            owner.core.record_write(key.namespace, key.identity)
            return put
        filler = b"x" * (owner.config.max_entry_bytes // 2)
        for offset in range(owner.config.budget_bytes // len(filler) + 1):
            capture = owner.core.begin_identity_admission(
                key.namespace, f"race-filler-{offset}"
            )
            owner.core.admit_identity_encoded(capture, key.read_shape, filler)
        return put

    WeightedLru.conditional_put = racing  # type: ignore[method-assign,assignment]


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
    "pause-server": lambda owner, _proxy, request: owner.pause(
        cast("float", request["seconds"])
    ),
    "pause-watch": lambda _owner, proxy, _request: proxy.pause(),
    "resume-watch": lambda _owner, proxy, _request: proxy.resume(),
    "sever": lambda _owner, proxy, _request: proxy.sever(),
    "lose-history": lambda owner, _proxy, _request: owner.lose_history(
        owner.config.databases[0]
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


def owner_main(config: OwnerConfig, control: Connection) -> None:
    with proxy_for(config.mongodb_uri) as proxy:
        owner = SharedCacheOwner(
            replace(config, mongodb_uri=f"mongodb://127.0.0.1:{proxy.local_port}")
        )
        try:
            owner.bind()
            control.send({"kind": "ready", "pid": os.getpid(), **process_sample()})
            owner.serve(control, lambda request: _control(owner, proxy, request))
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
