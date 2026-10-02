from __future__ import annotations

import socket
import threading
import time
from typing import TYPE_CHECKING, Any

import pytest

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.errors import (
    BenchmarkConfigurationError,
    BenchmarkSetupError,
)
from benchmarks.stream_cost.proxy import (
    DIRECT_PATH_BYTES_LIMITATION,
    DirectPathByteProxy,
    DirectPathProxyConfig,
)

if TYPE_CHECKING:
    from collections.abc import Iterator

pytestmark = pytest.mark.unit


def _direct_topology(**overrides: object) -> BenchmarkClientTopologyConfig:
    defaults: dict[str, object] = {
        "tls_enabled": False,
        "compressor": WireCompressor.NONE,
        "discovery_enabled": False,
        "shared_connections": False,
    }
    defaults.update(overrides)
    return BenchmarkClientTopologyConfig(**defaults)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "override",
    [
        {"tls_enabled": True},
        {"discovery_enabled": True},
        {"shared_connections": True},
    ],
)
def test_proxy_config_rejects_unsupported_topology(override: dict[str, object]) -> None:
    with pytest.raises(BenchmarkConfigurationError):
        DirectPathProxyConfig(
            client_topology=_direct_topology(**override),
            upstream_host="127.0.0.1",
            upstream_port=1,
        )


def test_proxy_config_accepts_fully_direct_topology() -> None:
    DirectPathProxyConfig(
        client_topology=_direct_topology(), upstream_host="127.0.0.1", upstream_port=1
    )


@pytest.mark.parametrize(
    "compressor",
    [WireCompressor.SNAPPY, WireCompressor.ZLIB, WireCompressor.ZSTD],
)
def test_proxy_config_accepts_a_compressed_topology(compressor: WireCompressor) -> None:
    DirectPathProxyConfig(
        client_topology=_direct_topology(compressor=compressor),
        upstream_host="127.0.0.1",
        upstream_port=1,
    )


@pytest.fixture
def bound_socket() -> Iterator[socket.socket]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    yield listener
    listener.close()


@pytest.fixture
def echo_server(bound_socket: socket.socket) -> Iterator[int]:
    listener = bound_socket

    def _serve() -> None:
        connection, _ = listener.accept()
        with connection:
            while True:
                chunk = connection.recv(4096)
                if not chunk:
                    return
                connection.sendall(chunk)

    thread = threading.Thread(target=_serve, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    listener.close()
    thread.join(timeout=5)


def test_proxy_forwards_and_counts_direct_path_bytes(echo_server: int) -> None:
    config = DirectPathProxyConfig(
        client_topology=_direct_topology(),
        upstream_host="127.0.0.1",
        upstream_port=echo_server,
    )
    payload = b"stream-cost-benchmark"
    with DirectPathByteProxy(config) as proxy:
        assert proxy.limitation == DIRECT_PATH_BYTES_LIMITATION
        with socket.create_connection(("127.0.0.1", proxy.local_port)) as client:
            client.sendall(payload)
            received = client.recv(len(payload))
            assert received == payload

        deadline = time.monotonic() + 2
        while (
            proxy.bytes_sent < len(payload) or proxy.bytes_received < len(payload)
        ) and time.monotonic() < deadline:
            time.sleep(0.01)  # pragma: no cover (rare pump-thread scheduling race)

        assert proxy.bytes_sent == len(payload)
        assert proxy.bytes_received == len(payload)

        reclaim_deadline = time.monotonic() + 2
        while (
            proxy._sockets or proxy._connection_threads
        ) and time.monotonic() < reclaim_deadline:
            time.sleep(0.01)  # pragma: no cover (rare pump-thread scheduling race)

        assert proxy._sockets == []
        assert proxy._connection_threads == []


def _proxy_config(upstream_port: int = 1) -> DirectPathProxyConfig:
    return DirectPathProxyConfig(
        client_topology=_direct_topology(),
        upstream_host="127.0.0.1",
        upstream_port=upstream_port,
    )


def test_exit_without_enter_is_a_noop() -> None:
    DirectPathByteProxy(_proxy_config()).__exit__()


def test_exit_tolerates_a_tracked_socket_that_is_already_closed() -> None:
    closed_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    closed_socket.close()
    proxy = DirectPathByteProxy(_proxy_config())
    proxy._sockets.append(closed_socket)

    proxy.__exit__()


def test_local_port_before_start_raises() -> None:
    proxy = DirectPathByteProxy(_proxy_config())
    with pytest.raises(BenchmarkSetupError, match="has not been started"):
        _ = proxy.local_port


def test_accept_loop_exits_immediately_when_already_stopping(
    bound_socket: socket.socket,
) -> None:
    proxy = DirectPathByteProxy(_proxy_config())
    proxy._listener = bound_socket
    proxy._stopping.set()
    proxy._accept_loop()


def test_accept_loop_bounds_the_upstream_connect_timeout(
    monkeypatch: pytest.MonkeyPatch,
    bound_socket: socket.socket,
) -> None:
    listener = bound_socket

    real_create_connection = socket.create_connection
    captured_kwargs: dict[str, Any] = {}

    def _capturing_create_connection(
        _address: object, **kwargs: object
    ) -> socket.socket:
        captured_kwargs.update(kwargs)
        message = "stubbed upstream connect"
        raise OSError(message)

    monkeypatch.setattr(socket, "create_connection", _capturing_create_connection)

    proxy = DirectPathByteProxy(_proxy_config(upstream_port=1))
    proxy._listener = listener
    thread = threading.Thread(target=proxy._accept_loop, daemon=True)
    thread.start()
    try:
        with real_create_connection(("127.0.0.1", listener.getsockname()[1])):
            deadline = time.monotonic() + 2
            while not captured_kwargs and time.monotonic() < deadline:
                time.sleep(
                    0.01
                )  # pragma: no cover (rare accept-thread scheduling race)
    finally:
        proxy._stopping.set()
        listener.close()
        thread.join(timeout=5)

    assert captured_kwargs["timeout"] == pytest.approx(2.0)


def test_accept_loop_continues_after_accept_timeout(
    bound_socket: socket.socket,
) -> None:
    listener = bound_socket
    listener.settimeout(0.01)

    proxy = DirectPathByteProxy(_proxy_config())
    proxy._listener = listener
    thread = threading.Thread(target=proxy._accept_loop, daemon=True)
    thread.start()
    time.sleep(0.05)
    proxy._stopping.set()
    listener.close()
    thread.join(timeout=5)


def test_accept_loop_returns_when_listener_is_closed() -> None:
    proxy = DirectPathByteProxy(_proxy_config())
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.close()
    proxy._listener = listener
    proxy._accept_loop()


def test_accept_loop_closes_client_when_upstream_unreachable(
    bound_socket: socket.socket,
) -> None:
    listener = bound_socket

    probe = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    probe.bind(("127.0.0.1", 0))
    unreachable_port = probe.getsockname()[1]  # pytriage: TR5
    probe.close()

    proxy = DirectPathByteProxy(_proxy_config(upstream_port=unreachable_port))
    proxy._listener = listener
    thread = threading.Thread(target=proxy._accept_loop, daemon=True)
    thread.start()
    try:
        with socket.create_connection(
            ("127.0.0.1", listener.getsockname()[1])
        ) as client:
            assert client.recv(1) == b""
    finally:
        proxy._stopping.set()
        listener.close()
        thread.join(timeout=5)

    assert proxy._sockets == []
    assert proxy._connection_threads == []


def test_exit_force_closes_and_joins_still_active_connections(
    bound_socket: socket.socket,
) -> None:
    upstream_listener = bound_socket
    accepted: list[socket.socket] = []

    def _accept_and_hold() -> None:
        connection, _ = upstream_listener.accept()
        accepted.append(connection)

    upstream_thread = threading.Thread(target=_accept_and_hold, daemon=True)
    upstream_thread.start()

    config = DirectPathProxyConfig(
        client_topology=_direct_topology(),
        upstream_host="127.0.0.1",
        upstream_port=upstream_listener.getsockname()[1],
    )
    proxy = DirectPathByteProxy(config)
    proxy.__enter__()
    client = socket.create_connection(("127.0.0.1", proxy.local_port))
    try:
        deadline = time.monotonic() + 2
        while not proxy._sockets and time.monotonic() < deadline:
            time.sleep(0.01)  # pragma: no cover (rare accept-thread scheduling race)
        assert proxy._sockets
        assert proxy._connection_threads
    finally:
        proxy.__exit__()
        client.close()
        upstream_thread.join(timeout=5)
        upstream_listener.close()
        for sock in accepted:
            sock.close()


def test_pump_returns_on_send_error() -> None:
    proxy = DirectPathByteProxy(_proxy_config())
    source_read, source_write = socket.socketpair()
    destination = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    destination.close()
    try:
        source_write.sendall(b"data")
        proxy._pump(source_read, destination, is_sent=True)
    finally:
        source_read.close()
        source_write.close()
