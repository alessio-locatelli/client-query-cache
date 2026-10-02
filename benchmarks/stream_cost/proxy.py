from __future__ import annotations

import socket
import threading
from dataclasses import dataclass
from typing import TYPE_CHECKING, Self

from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)

if TYPE_CHECKING:
    from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig

DIRECT_PATH_BYTES_LIMITATION = (
    "counts bytes only on this proxy's direct benchmark path between the "
    "dedicated client and the replica-set primary; not a substitute for "
    "universal wire-traffic accounting"
)

_BUFFER_SIZE = 65_536
_JOIN_TIMEOUT_SECONDS = 5.0
_ACCEPT_POLL_INTERVAL_SECONDS = 0.5
_UPSTREAM_CONNECT_TIMEOUT_SECONDS = 2.0


@dataclass(frozen=True, slots=True)
class DirectPathProxyConfig:
    client_topology: BenchmarkClientTopologyConfig
    upstream_host: str
    upstream_port: int

    def __post_init__(self) -> None:
        topology = self.client_topology
        if topology.tls_enabled:
            message = "direct-path byte proxy does not support TLS-enabled clients"
            raise BenchmarkConfigurationError(message)
        if topology.discovery_enabled:
            message = "direct-path byte proxy does not support topology discovery"
            raise BenchmarkConfigurationError(message)
        if topology.shared_connections:
            message = "direct-path byte proxy does not support shared connections"
            raise BenchmarkConfigurationError(message)


class DirectPathByteProxy:
    __slots__ = (
        "_accept_thread",
        "_bytes_received",
        "_bytes_sent",
        "_config",
        "_connection_threads",
        "_listener",
        "_lock",
        "_sockets",
        "_stopping",
    )

    def __init__(self, config: DirectPathProxyConfig) -> None:
        self._config = config
        self._bytes_sent = 0
        self._bytes_received = 0
        self._lock = threading.Lock()
        self._listener: socket.socket | None = None
        self._accept_thread: threading.Thread | None = None
        self._connection_threads: list[threading.Thread] = []
        self._sockets: list[socket.socket] = []
        self._stopping = threading.Event()

    def __enter__(self) -> Self:
        listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener.bind(("127.0.0.1", 0))
        listener.listen()
        listener.settimeout(_ACCEPT_POLL_INTERVAL_SECONDS)
        self._listener = listener
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()
        return self

    def __exit__(self, *_exc_info: object) -> None:
        self._stopping.set()
        if self._listener is not None:
            self._listener.close()
        if self._accept_thread is not None:
            self._accept_thread.join(timeout=_JOIN_TIMEOUT_SECONDS)
        with self._lock:
            sockets = list(self._sockets)
            connection_threads = list(self._connection_threads)
        for sock in sockets:
            try:
                sock.shutdown(socket.SHUT_RDWR)
            except OSError:
                pass
            sock.close()
        for thread in connection_threads:
            thread.join(timeout=_JOIN_TIMEOUT_SECONDS)

    @property
    def local_port(self) -> int:
        if self._listener is None:
            message = "DirectPathByteProxy has not been started"
            raise BenchmarkSetupError(message)
        port: int = self._listener.getsockname()[1]
        return port

    @property
    def bytes_sent(self) -> int:
        with self._lock:
            return self._bytes_sent

    @property
    def bytes_received(self) -> int:
        with self._lock:
            return self._bytes_received

    @property
    def limitation(self) -> str:
        return DIRECT_PATH_BYTES_LIMITATION

    def _accept_loop(self) -> None:
        listener = self._listener
        assert listener is not None
        while not self._stopping.is_set():
            try:
                client_socket, _ = listener.accept()
            except TimeoutError:
                continue
            except OSError:
                return
            try:
                upstream_socket = socket.create_connection(
                    (self._config.upstream_host, self._config.upstream_port),
                    timeout=_UPSTREAM_CONNECT_TIMEOUT_SECONDS,
                )
                upstream_socket.settimeout(None)
            except OSError:
                client_socket.close()
                continue
            connection_thread = threading.Thread(
                target=self._run_connection,
                args=(client_socket, upstream_socket),
                daemon=True,
            )
            with self._lock:
                self._sockets.extend((client_socket, upstream_socket))
                self._connection_threads.append(connection_thread)
            connection_thread.start()

    def _run_connection(
        self, client_socket: socket.socket, upstream_socket: socket.socket
    ) -> None:
        pumps = [
            threading.Thread(
                target=self._pump,
                args=(source, destination),
                kwargs={"is_sent": is_sent},
                daemon=True,
            )
            for source, destination, is_sent in (
                (client_socket, upstream_socket, True),
                (upstream_socket, client_socket, False),
            )
        ]
        for pump in pumps:
            pump.start()
        for pump in pumps:
            pump.join()
        for sock in (client_socket, upstream_socket):
            sock.close()
        with self._lock:
            self._sockets.remove(client_socket)
            self._sockets.remove(upstream_socket)
            self._connection_threads.remove(threading.current_thread())

    def _pump(
        self, source: socket.socket, destination: socket.socket, *, is_sent: bool
    ) -> None:
        try:
            self._relay(source, destination, is_sent=is_sent)
        except OSError:
            return
        finally:
            try:
                destination.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def _relay(
        self, source: socket.socket, destination: socket.socket, *, is_sent: bool
    ) -> None:
        while True:
            chunk = source.recv(_BUFFER_SIZE)
            if not chunk:
                return
            destination.sendall(chunk)
            with self._lock:
                if is_sent:
                    self._bytes_sent += len(chunk)
                else:
                    self._bytes_received += len(chunk)
