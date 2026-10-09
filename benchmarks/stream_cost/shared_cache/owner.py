# Research prototype owner process and fault hooks.
from __future__ import annotations

import os
import socket
import threading
import time
from dataclasses import asdict, replace
from typing import TYPE_CHECKING, override
from urllib.parse import urlsplit

import psutil

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.proxy import DirectPathByteProxy, DirectPathProxyConfig
from benchmarks.stream_cost.shared_cache.coordinator import SharedCacheOwner

if TYPE_CHECKING:
    from multiprocessing.connection import Connection

    from benchmarks.stream_cost.shared_cache.coordinator import Message, OwnerConfig

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
            except OSError:
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


def _control(
    owner: SharedCacheOwner, proxy: FaultableProxy, request: Message
) -> Message | None:
    operation = request["op"]
    database = owner.config.databases[0]
    match operation:
        case "sample":
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
            }
        case "reset":
            owner.core.reset_stream_cost_statistics(database)
            return {"ok": True}
        case "pause-server":
            owner.pause(float(request["seconds"]))  # type: ignore[arg-type]
        case "pause-watch":
            proxy.pause()
        case "resume-watch":
            proxy.resume()
        case "sever":
            proxy.sever()
        case "lose-history":
            owner.lose_history(database)
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
        finally:
            proxy.resume()
            owner.close()
            control.send({"kind": "closed"})
            control.close()
