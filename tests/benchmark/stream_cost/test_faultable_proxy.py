from __future__ import annotations

import socket
import threading
import time
from typing import TYPE_CHECKING, cast

import pytest

from benchmarks.stream_cost.client import BenchmarkClientTopologyConfig, WireCompressor
from benchmarks.stream_cost.proxy import DirectPathProxyConfig
from benchmarks.stream_cost.shared_cache.owner import FaultableProxy
from tests.polling import wait_until

if TYPE_CHECKING:
    from collections.abc import Iterator

    from faker import Faker

    from client_query_cache._types import NonNegativeInt

pytestmark = pytest.mark.unit

_BUFFER_OVERFLOW_BYTES = 200_000
_SOCKET_TIMEOUT_SECONDS = 5.0
_PAUSE_QUIET_SECONDS = 0.2
_HALF_CLOSE_REPLY_BYTES = 64


@pytest.fixture
def upstream_port() -> Iterator[NonNegativeInt]:
    listener = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    listener.bind(("127.0.0.1", 0))
    listener.listen()
    served: list[bytes] = []

    def serve() -> None:
        connection, _ = listener.accept()
        with connection:
            received = bytearray()
            while chunk := connection.recv(65_536):
                received.extend(chunk)
            served.append(bytes(received))
            connection.sendall(b"r" * _HALF_CLOSE_REPLY_BYTES)

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    yield listener.getsockname()[1]
    listener.close()
    thread.join(timeout=_SOCKET_TIMEOUT_SECONDS)


@pytest.fixture
def proxy_config(upstream_port: NonNegativeInt) -> DirectPathProxyConfig:
    topology = BenchmarkClientTopologyConfig(
        tls_enabled=False,
        compressor=WireCompressor.NONE,
        discovery_enabled=False,
        shared_connections=False,
    )
    return DirectPathProxyConfig(topology, "127.0.0.1", upstream_port)


@pytest.fixture
def proxy(proxy_config: DirectPathProxyConfig) -> Iterator[FaultableProxy]:
    with FaultableProxy(proxy_config) as started:
        yield started


@pytest.fixture
def client(proxy: FaultableProxy) -> Iterator[socket.socket]:
    with socket.create_connection(("127.0.0.1", proxy.local_port)) as connection:
        connection.settimeout(_SOCKET_TIMEOUT_SECONDS)
        wait_until(lambda: len(proxy._sockets) == 2)
        yield connection


def test_a_half_closed_large_request_is_counted_before_the_reply(
    proxy: FaultableProxy, client: socket.socket, faker: Faker
) -> None:
    request = faker.binary(length=_BUFFER_OVERFLOW_BYTES)
    client.sendall(request)
    client.shutdown(socket.SHUT_WR)
    with client.makefile("rb") as replies:
        assert replies.read() == b"r" * _HALF_CLOSE_REPLY_BYTES

    wait_until(lambda: proxy.bytes_received == _HALF_CLOSE_REPLY_BYTES)
    assert proxy.bytes_sent == len(request)


class _ChunkedSource:
    __slots__ = ("_chunks",)

    def __init__(self, chunk: bytes) -> None:
        self._chunks = [chunk]

    def recv(self, _size: int) -> bytes:
        return self._chunks.pop() if self._chunks else b""


class _PartialSocket:
    __slots__ = ("_written",)

    def __init__(self, written: NonNegativeInt) -> None:
        self._written = written

    def send(self, chunk: memoryview) -> int:
        if self._written == 0:
            raise ConnectionResetError
        written = min(self._written, len(chunk))
        self._written -= written
        return written


def test_an_interrupted_send_counts_the_bytes_already_written(
    proxy_config: DirectPathProxyConfig, faker: Faker
) -> None:
    chunk = faker.binary(length=_HALF_CLOSE_REPLY_BYTES)
    accepted = _HALF_CLOSE_REPLY_BYTES // 4
    proxy = FaultableProxy(proxy_config)

    with pytest.raises(ConnectionResetError):
        proxy._relay(
            cast("socket.socket", _ChunkedSource(chunk)),
            cast("socket.socket", _PartialSocket(accepted)),
            is_sent=True,
        )

    assert proxy.bytes_sent == accepted


def test_pause_holds_traffic_until_resume(
    proxy: FaultableProxy, client: socket.socket, faker: Faker
) -> None:
    request = faker.binary(length=_HALF_CLOSE_REPLY_BYTES)
    proxy.pause()
    client.sendall(request)
    client.shutdown(socket.SHUT_WR)
    time.sleep(_PAUSE_QUIET_SECONDS)
    assert proxy.bytes_sent == 0

    proxy.resume()
    with client.makefile("rb") as replies:
        assert replies.read() == b"r" * _HALF_CLOSE_REPLY_BYTES

    wait_until(lambda: proxy.bytes_sent == len(request))


def test_teardown_wakes_senders_that_are_paused(
    proxy_config: DirectPathProxyConfig, faker: Faker
) -> None:
    with FaultableProxy(proxy_config) as proxy:
        proxy.pause()
        with socket.create_connection(("127.0.0.1", proxy.local_port)) as client:
            client.sendall(faker.binary(length=_HALF_CLOSE_REPLY_BYTES))
            wait_until(lambda: len(proxy._sockets) == 2)

    assert proxy._connection_threads == []


def test_sever_closes_every_connection(
    proxy: FaultableProxy, client: socket.socket
) -> None:
    proxy.sever()

    assert client.recv(1) == b""
